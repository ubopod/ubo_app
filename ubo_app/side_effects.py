"""Application logic."""

from __future__ import annotations

import atexit
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from redux import FinishAction

from ubo_app.store.core import PowerOffEvent, RebootEvent
from ubo_app.store.main import (
    ScreenshotEvent,
    SnapshotEvent,
    dispatch,
    store,
    subscribe_event,
)
from ubo_app.store.services.audio import AudioPlayChimeAction
from ubo_app.store.services.notifications import Chime
from ubo_app.store.update_manager import (
    UpdateManagerCheckEvent,
    UpdateManagerSetStatusAction,
    UpdateManagerUpdateEvent,
    UpdateStatus,
)
from ubo_app.store.update_manager.utils import check_version, update
from ubo_app.utils.hardware import IS_RPI, initialize_board

if TYPE_CHECKING:
    from numpy._typing import NDArray


def power_off() -> None:
    """Power off the device."""
    dispatch(AudioPlayChimeAction(name=Chime.FAILURE), FinishAction())
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
    dispatch(AudioPlayChimeAction(name=Chime.FAILURE), FinishAction())
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

    png.Writer(
        width=array.shape[0],
        height=array.shape[1],
        greyscale=False,  # pyright: ignore [reportArgumentType]
        bitdepth=8,
    ).write(
        image_path.open('wb'),
        array.reshape(-1, array.shape[0] * 3).tolist(),
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
    path = Path('snapshot.json')
    path.write_text(json.dumps(store.snapshot, indent=2))


def setup_side_effects() -> None:
    """Set up the application."""
    initialize_board()

    subscribe_event(PowerOffEvent, power_off)
    subscribe_event(RebootEvent, reboot)
    subscribe_event(UpdateManagerUpdateEvent, update)
    subscribe_event(UpdateManagerCheckEvent, check_version)
    subscribe_event(ScreenshotEvent, take_screenshot)
    subscribe_event(SnapshotEvent, take_snapshot)

    dispatch(UpdateManagerSetStatusAction(status=UpdateStatus.CHECKING))
