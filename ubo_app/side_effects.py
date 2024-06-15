"""Application logic."""

from __future__ import annotations

import atexit
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from debouncer import DebounceOptions, debounce
from redux import FinishAction

from ubo_app.store.core import PowerOffEvent
from ubo_app.store.main import (
    ScreenshotEvent,
    SnapshotEvent,
    dispatch,
    store,
    subscribe_event,
)
from ubo_app.store.services.notifications import Chime
from ubo_app.store.services.sound import SoundPlayChimeAction
from ubo_app.store.update_manager import (
    UpdateManagerCheckEvent,
    UpdateManagerSetStatusAction,
    UpdateManagerUpdateEvent,
    UpdateStatus,
)
from ubo_app.store.update_manager.utils import check_version, update
from ubo_app.utils.async_ import create_task
from ubo_app.utils.hardware import (
    IS_RPI,
    initialize_board,
    turn_off_screen,
    turn_on_screen,
)

if TYPE_CHECKING:
    from numpy._typing import NDArray


def power_off() -> None:
    """Power off the device."""
    dispatch(SoundPlayChimeAction(name=Chime.FAILURE), FinishAction())
    if IS_RPI:
        atexit.register(
            lambda: subprocess.run(
                ['/usr/bin/env', 'systemctl', 'poweroff', '-i'],  # noqa: S603
                check=True,
            ),
        )


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
    import headless_kivy_pi.config

    counter = 0
    while (path := Path(f'screenshots/ubo-screenshot-{counter:03d}.png')).exists():
        counter += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    write_image(path, headless_kivy_pi.config._display.raw_data)  # noqa: SLF001


def take_snapshot() -> None:
    """Take a snapshot of the store."""
    path = Path('snapshot.json')
    path.write_text(json.dumps(store.snapshot, indent=2))


def setup_side_effects() -> None:
    """Set up the application."""
    turn_on_screen()
    initialize_board()

    subscribe_event(PowerOffEvent, power_off)
    subscribe_event(UpdateManagerUpdateEvent, update)
    subscribe_event(UpdateManagerCheckEvent, check_version)
    subscribe_event(ScreenshotEvent, take_screenshot)
    subscribe_event(SnapshotEvent, take_snapshot)

    @debounce(
        wait=10,
        options=DebounceOptions(leading=True, trailing=False, time_window=10),
    )
    async def request_check_version() -> None:
        dispatch(UpdateManagerSetStatusAction(status=UpdateStatus.CHECKING))

    create_task(request_check_version())

    atexit.register(turn_off_screen)
