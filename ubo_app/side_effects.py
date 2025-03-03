"""Side effects for the application."""

from __future__ import annotations

import asyncio
import atexit
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from redux import FinishAction, FinishEvent

from ubo_app import display
from ubo_app.constants import INSTALLATION_PATH
from ubo_app.logger import logger
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
from ubo_app.store.services.wifi import WiFiInputConnectionAction
from ubo_app.store.update_manager.types import (
    UpdateManagerCheckEvent,
    UpdateManagerSetStatusAction,
    UpdateManagerUpdateEvent,
    UpdateStatus,
)
from ubo_app.store.update_manager.utils import check_version, update
from ubo_app.utils.async_ import create_task
from ubo_app.utils.hardware import IS_RPI, initialize_board
from ubo_app.utils.network import get_saved_wifi_ssids, has_gateway
from ubo_app.utils.store import replay_actions

if TYPE_CHECKING:
    from numpy._typing import NDArray


def power_off() -> None:
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


def reboot() -> None:
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


def write_image(image_path: Path, array: NDArray) -> None:
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


def take_screenshot() -> None:
    """Take a screenshot of the screen."""
    from headless_kivy import HeadlessWidget

    counter = 0
    while (path := Path(f'screenshots/ubo-screenshot-{counter:03d}.png')).exists():
        counter += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    write_image(path, HeadlessWidget.raw_data)


def take_snapshot() -> None:
    """Take a snapshot of the store."""
    counter = 0
    while (path := Path(f'snapshots/ubo-screenshot-{counter:03d}.json')).exists():
        counter += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as file:
        json.dump(store.snapshot, file, indent=2)


def store_recorded_sequence(event: StoreRecordedSequenceEvent) -> None:
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


async def replay_recorded_sequence() -> None:
    """Replay the recorded sequence."""
    await replay_actions(store, Path('recordings/active.json'))


async def check_wifi() -> None:
    """Dispatch the Wi-Fi input action if needed."""
    await asyncio.sleep(10)
    logger.info(
        'Checking Wi-Fi',
        extra={
            'has_gateway': await has_gateway(),
            'saved_wifi_ssids': await get_saved_wifi_ssids(),
        },
    )
    if not await has_gateway() and not await get_saved_wifi_ssids():
        logger.info('No network connection found, prompting for Wi-Fi input')
        store.dispatch(WiFiInputConnectionAction())


def setup_side_effects() -> None:
    """Set up the side effects for the application."""
    initialize_board()

    store.subscribe_event(FinishEvent, display.turn_off)
    store.subscribe_event(PowerOffEvent, power_off)
    store.subscribe_event(RebootEvent, reboot)
    store.subscribe_event(UpdateManagerUpdateEvent, update)
    store.subscribe_event(UpdateManagerCheckEvent, check_version)
    store.subscribe_event(ScreenshotEvent, take_screenshot)
    store.subscribe_event(SnapshotEvent, take_snapshot)
    store.subscribe_event(StoreRecordedSequenceEvent, store_recorded_sequence)
    store.subscribe_event(ReplayRecordedSequenceEvent, replay_recorded_sequence)

    store.dispatch(UpdateManagerSetStatusAction(status=UpdateStatus.CHECKING))

    create_task(check_wifi())

    # Create a file signaling that the app is ready
    if IS_RPI:
        Path(INSTALLATION_PATH).mkdir(parents=True, exist_ok=True)
        (Path(INSTALLATION_PATH) / 'app_ready').touch()
