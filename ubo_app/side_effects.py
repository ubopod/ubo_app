"""Application logic."""
from __future__ import annotations

import atexit
import subprocess
from typing import TYPE_CHECKING, Sequence

from debouncer import DebounceOptions, debounce
from headless_kivy_pi.constants import BYTES_PER_PIXEL
from redux import FinishAction, FinishEvent

from ubo_app.store import autorun, dispatch, subscribe_event
from ubo_app.store.main import PowerOffEvent
from ubo_app.store.update_manager import (
    CheckVersionEvent,
    SetUpdateStatusAction,
    UpdateStatus,
    UpdateVersionEvent,
)
from ubo_app.store.update_manager.reducer import ABOUT_MENU_PATH
from ubo_app.store.update_manager.utils import check_version, update
from ubo_app.utils import initialize_board, turn_off_screen, turn_on_screen
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from ubo_app.menu import MenuApp


def power_off(_: PowerOffEvent) -> None:
    """Power off the device."""
    from headless_kivy_pi import HeadlessWidget

    display = HeadlessWidget._display  # noqa: SLF001
    data = [0] * HeadlessWidget.width * HeadlessWidget.height * BYTES_PER_PIXEL
    display._block(0, 0, HeadlessWidget.width - 1, HeadlessWidget.height - 1, data)  # noqa: SLF001
    subprocess.run(['/usr/bin/env', 'systemctl', 'poweroff', '-i'], check=True)  # noqa: S603

    dispatch(FinishAction())


def setup(app: MenuApp) -> None:
    """Set up the application."""
    turn_on_screen()
    initialize_board()

    subscribe_event(PowerOffEvent, power_off)
    subscribe_event(FinishEvent, lambda *_: app.stop())
    subscribe_event(UpdateVersionEvent, lambda: create_task(update()))
    subscribe_event(CheckVersionEvent, lambda: create_task(check_version()))

    @debounce(
        wait=10,
        options=DebounceOptions(leading=True, trailing=False, time_window=10),
    )
    async def request_check_version() -> None:
        dispatch(SetUpdateStatusAction(status=UpdateStatus.CHECKING))

    @autorun(lambda state: state.main.path)
    async def check_version_caller(
        path: Sequence[str],
        previous_path: Sequence[str],
    ) -> None:
        if path != previous_path and path[:3] == ABOUT_MENU_PATH:
            create_task(request_check_version())

    check_version_caller.subscribe(create_task)
    create_task(request_check_version())

    atexit.register(turn_off_screen)
