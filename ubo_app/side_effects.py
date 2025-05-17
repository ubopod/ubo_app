"""Side effects for the application."""

from __future__ import annotations

import atexit
import json
import signal
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from redux import FinishAction

from ubo_app.store.core.types import (
    PowerOffEvent,
    RebootEvent,
    ReplayRecordedSequenceEvent,
    ScreenshotEvent,
    SnapshotEvent,
    StoreRecordedSequenceEvent,
)
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioPlayChimeAction
from ubo_app.store.services.notifications import Chime
from ubo_app.store.update_manager.types import (
    UpdateManagerCheckEvent,
    UpdateManagerRequestCheckAction,
    UpdateManagerUpdateEvent,
)
from ubo_app.store.update_manager.utils import check_version, update
from ubo_app.utils import bus_provider
from ubo_app.utils.hardware import IS_RPI, deinitalize_board, initialize_board
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.store import replay_actions

if TYPE_CHECKING:
    from numpy._typing._array_like import NDArray

    from ubo_app.utils.types import Subscriptions


def _power_off() -> None:
    """Power off the device."""
    store.dispatch(AudioPlayChimeAction(name=Chime.FAILURE), FinishAction())
    if IS_RPI:

        def power_off_system(*_: list[object]) -> None:
            atexit.unregister(power_off_system)
            atexit._run_exitfuncs()  # noqa: SLF001
            subprocess.run(  # noqa: S603
                ['/usr/bin/env', 'systemctl', 'poweroff', '-i'],
                check=True,
            )

        atexit.register(power_off_system)


def _reboot() -> None:
    """Reboot the device."""
    store.dispatch(AudioPlayChimeAction(name=Chime.FAILURE), FinishAction())
    if IS_RPI:

        def reboot_system(*_: list[object]) -> None:
            atexit.unregister(reboot_system)
            atexit._run_exitfuncs()  # noqa: SLF001
            subprocess.run(  # noqa: S603
                ['/usr/bin/env', 'systemctl', 'reboot', '-i'],
                check=True,
            )

        atexit.register(reboot_system)


def _write_image(image_path: Path, array: NDArray) -> None:
    """Write the `NDAarray` as an image to the given path."""
    import png

    array = np.flipud(array)

    png.Writer(
        alpha=True,
        width=array.shape[0],
        height=array.shape[1],
        greyscale=False,  # pyright: ignore [reportArgumentType]
        bitdepth=8,
    ).write(
        image_path.open('wb'),
        array.reshape(-1, array.shape[1] * 4).tolist(),
    )


def _take_screenshot() -> None:
    """Take a screenshot of the screen."""
    from headless_kivy import HeadlessWidget

    counter = 0
    while (path := Path(f'screenshots/ubo-screenshot-{counter:03d}.png')).exists():
        counter += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_image(path, HeadlessWidget.raw_data)


def _take_snapshot() -> None:
    """Take a snapshot of the store."""
    counter = 0
    while (path := Path(f'snapshots/ubo-screenshot-{counter:03d}.json')).exists():
        counter += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as file:
        json.dump(store.snapshot, file, indent=2)


def _store_recorded_sequence(event: StoreRecordedSequenceEvent) -> None:
    """Store the recorded sequence."""
    counter = 0
    while (path := Path(f'recordings/ubo-recording-{counter:03d}.json')).exists():
        counter += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    json_dump = json.dumps(
        [
            store.serialize_value(action)
            for action in event.recorded_sequence
            if type(action).__name__.startswith('Keypad')
        ],
        indent=2,
    )

    with path.open('w') as file:
        file.write(json_dump)
    with Path('recordings/active.json').open('w') as file:
        file.write(json_dump)


async def _replay_recorded_sequence() -> None:
    """Replay the recorded sequence."""
    await replay_actions(store, Path('recordings/active.json'))


def setup_side_effects() -> Subscriptions:
    """Set up the side effects for the application."""
    initialize_board()

    register_persistent_store(
        'services',
        lambda state: None
        if state.settings.services is None
        else [
            {
                'id': service.id,
                'is_enabled': service.is_enabled,
                'log_level': service.log_level,
                'should_auto_restart': service.should_auto_restart,
            }
            for service in state.settings.services.values()
        ],
    )
    register_persistent_store(
        'settings:pdb_signal',
        lambda state: state.settings.pdb_signal,
    )
    register_persistent_store(
        'settings:visual_debug',
        lambda state: state.settings.visual_debug,
    )
    register_persistent_store(
        'settings:beta_versions',
        lambda state: state.settings.beta_versions,
    )
    subscriptions = [
        store.subscribe_event(PowerOffEvent, _power_off),
        store.subscribe_event(RebootEvent, _reboot),
        store.subscribe_event(UpdateManagerUpdateEvent, update),
        store.subscribe_event(UpdateManagerCheckEvent, check_version),
        store.subscribe_event(ScreenshotEvent, _take_screenshot),
        store.subscribe_event(SnapshotEvent, _take_snapshot),
        store.subscribe_event(StoreRecordedSequenceEvent, _store_recorded_sequence),
        store.subscribe_event(ReplayRecordedSequenceEvent, _replay_recorded_sequence),
        deinitalize_board,
        bus_provider.clean_up,
    ]

    from kivy.clock import mainthread

    @store.autorun(lambda state: state.settings.pdb_signal)
    @mainthread
    def _pdb_debug_mode(pdb_signal: bool) -> None:  # noqa: FBT001
        """Set the PDB debug mode."""

        def signal_handler(signum: int, _: object) -> None:
            if signum == signal.SIGUSR1:
                import ipdb  # noqa: T100

                ipdb.set_trace()  # noqa: T100
                return

        if pdb_signal:
            signal.signal(signal.SIGUSR1, signal_handler)
        else:
            signal.signal(signal.SIGUSR1, signal.SIG_DFL)

    store.dispatch(UpdateManagerRequestCheckAction())

    return subscriptions
