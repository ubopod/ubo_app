"""Side effects for the application."""

from __future__ import annotations

import atexit
import functools
import json
import signal
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from redux import FinishAction

from ubo_app.store.core.types import (
    PowerOffEvent,
    RebootEvent,
    ReplayRecordedSequenceEvent,
    ScreenshotDataEvent,
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
from ubo_app.utils.async_ import create_task
from ubo_app.utils.hardware import IS_RPI
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
            subprocess.run(
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
            subprocess.run(
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
    """Take a screenshot of the screen.

    Only works when Kivy is running in-process (HeadlessWidget.raw_data available).
    When Kivy runs in a GUI subprocess, screenshots are handled via gRPC round-trip
    (ScreenshotEvent → GUI client → ScreenshotDataAction → ScreenshotDataEvent).
    """
    try:
        from headless_kivy import HeadlessWidget
    except ImportError:
        from ubo_app.logger import logger

        logger.warning('Cannot take screenshot: headless_kivy not available')
        return

    if not hasattr(HeadlessWidget, 'raw_data') or HeadlessWidget.raw_data is None:
        from ubo_app.logger import logger

        logger.debug(
            'Skipping in-process screenshot: HeadlessWidget.raw_data not available'
            ' (Kivy may be running in a subprocess)',
        )
        return

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
        [store.serialize_value(action) for action in event.recorded_sequence],
        indent=2,
    )

    with path.open('w') as file:
        file.write(json_dump)
    with Path('recordings/active.json').open('w') as file:
        file.write(json_dump)


def _save_screenshot_data(event: ScreenshotDataEvent) -> None:
    """Save screenshot data received from GUI client to disk.

    Skipped in test environments to avoid filesystem churn from stability
    polling screenshots.
    """
    from ubo_app.utils import IS_TEST_ENV

    if IS_TEST_ENV:
        return
    counter = 0
    while (path := Path(f'screenshots/ubo-screenshot-{counter:03d}.png')).exists():
        counter += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as f:
        f.write(event.data)


async def _replay_recorded_sequence() -> None:
    """Replay the recorded sequence."""
    await replay_actions(store, Path('recordings/active.json'))


def setup_side_effects() -> Subscriptions:
    """Set up the side effects for the application."""
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
    register_persistent_store(
        'settings:grpc_remote_access',
        lambda state: state.settings.grpc_remote_access,
    )
    register_persistent_store(
        'settings:assistant_debug',
        lambda state: state.settings.assistant_debug,
    )
    register_persistent_store(
        'settings:tcp_lite_enabled',
        lambda state: state.settings.tcp_lite_enabled,
    )
    subscriptions = [
        store.subscribe_event(PowerOffEvent, _power_off),
        store.subscribe_event(RebootEvent, _reboot),
        store.subscribe_event(UpdateManagerUpdateEvent, update),
        store.subscribe_event(UpdateManagerCheckEvent, check_version),
        store.subscribe_event(ScreenshotEvent, _take_screenshot),
        store.subscribe_event(ScreenshotDataEvent, _save_screenshot_data),
        store.subscribe_event(SnapshotEvent, _take_snapshot),
        store.subscribe_event(StoreRecordedSequenceEvent, _store_recorded_sequence),
        store.subscribe_event(ReplayRecordedSequenceEvent, _replay_recorded_sequence),
        bus_provider.clean_up,
    ]

    def _to_main_thread(func):  # type: ignore[misc]  # noqa: ANN001, ANN202
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> None:
            if threading.current_thread() is threading.main_thread():
                func(*args, **kwargs)

        return wrapper

    @store.autorun(lambda state: state.settings.pdb_signal)
    @_to_main_thread
    def _pdb_debug_mode(pdb_signal: bool) -> None:  # noqa: FBT001
        """Set the PDB debug mode."""

        def pdb_signal_handler(signum: int, _: object) -> None:
            if signum == signal.SIGUSR1:
                import ipdb  # noqa: T100

                ipdb.set_trace()  # noqa: T100
                return

        if pdb_signal:
            signal.signal(signal.SIGUSR1, pdb_signal_handler)
        else:
            signal.signal(signal.SIGUSR1, signal.SIG_DFL)

    @store.autorun(lambda state: state.settings.tcp_lite_enabled)
    def _tcp_lite_server_toggle(enabled: bool) -> None:  # noqa: FBT001
        """Start or stop the MCU raw-TCP listener to match the setting."""
        from ubo_app.constants import DISABLE_MCU_SERVER
        from ubo_app.rpc import mcu_server

        create_task(
            mcu_server.serve()
            if enabled and not DISABLE_MCU_SERVER
            else mcu_server.close_server(),
        )

    store.dispatch(UpdateManagerRequestCheckAction())

    return subscriptions
