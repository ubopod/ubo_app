"""Application logic."""

from __future__ import annotations

import atexit
import subprocess
import weakref
from typing import TYPE_CHECKING, Sequence

from debouncer import DebounceOptions, debounce
from kivy.clock import mainthread
from redux import AutorunOptions, FinishAction, FinishEvent

from ubo_app.store import autorun, dispatch, subscribe_event
from ubo_app.store.main import PowerOffEvent
from ubo_app.store.services.notifications import Chime
from ubo_app.store.services.sound import SoundPlayChimeAction
from ubo_app.store.update_manager import (
    UpdateManagerCheckEvent,
    UpdateManagerSetStatusAction,
    UpdateManagerUpdateEvent,
    UpdateStatus,
)
from ubo_app.store.update_manager.reducer import ABOUT_MENU_PATH
from ubo_app.store.update_manager.utils import check_version, update
from ubo_app.utils.async_ import create_task
from ubo_app.utils.hardware import (
    IS_RPI,
    initialize_board,
    turn_off_screen,
    turn_on_screen,
)

if TYPE_CHECKING:
    from ubo_app.menu import MenuApp


def power_off() -> None:
    """Power off the device."""
    dispatch(SoundPlayChimeAction(name=Chime.FAILURE), FinishAction())
    if IS_RPI:
        subprocess.run(['/usr/bin/env', 'systemctl', 'poweroff', '-i'], check=True)  # noqa: S603


def setup(app: MenuApp) -> None:
    """Set up the application."""
    turn_on_screen()
    initialize_board()

    subscribe_event(PowerOffEvent, power_off)

    app_ref = weakref.ref(app)

    @mainthread
    def stop_app() -> None:
        app = app_ref()
        if app is not None:
            app.stop()

    subscribe_event(FinishEvent, stop_app)
    subscribe_event(UpdateManagerUpdateEvent, update)
    subscribe_event(UpdateManagerCheckEvent, check_version)

    @debounce(
        wait=10,
        options=DebounceOptions(leading=True, trailing=False, time_window=10),
    )
    async def request_check_version() -> None:
        dispatch(UpdateManagerSetStatusAction(status=UpdateStatus.CHECKING))

    @autorun(lambda state: state.main.path, options=AutorunOptions(keep_ref=False))
    def _(
        path: Sequence[str],
        previous_path: Sequence[str],
    ) -> None:
        if path != previous_path and path[:3] == ABOUT_MENU_PATH:
            create_task(request_check_version())

    create_task(request_check_version())

    atexit.register(turn_off_screen)
