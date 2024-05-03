# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import pathlib
import socket
import subprocess
from typing import TYPE_CHECKING

from checks import check_status
from constants import CODE_BINARY_PATH
from kivy.clock import mainthread
from kivy.lang.builder import Builder
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from ubo_gui.constants import DANGER_COLOR
from ubo_gui.menu.types import ActionItem
from ubo_gui.page import PageWidget

from ubo_app.store import autorun, dispatch
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task

CODE_TUNNEL_URL_PREFIX = 'https://vscode.dev/tunnel/'

if TYPE_CHECKING:
    from ubo_app.store.services.vscode import VSCodeState


class SetupPage(PageWidget):
    stage: int = NumericProperty(0)
    is_installed = BooleanProperty()
    url: str = StringProperty()

    def go_back(self: SetupPage) -> bool:
        if self.stage > 1:
            self.stage = 1
            return True
        return False

    def __init__(
        self: SetupPage,
        *args: object,
        **kwargs: object,
    ) -> None:
        items = [
            ActionItem(
                label='Set name',
                action=lambda: create_task(self.set_name()) and None,
            ),
            ActionItem(
                action=lambda: create_task(
                    self.uninstall_service()
                    if self.is_installed
                    else self.install_service(),
                )
                and None,
            ),
            ActionItem(
                label='Show URL',
                icon='󰐲',
                action=self.show_url,
            ),
        ]
        super().__init__(*args, **kwargs, items=items)

        autorun(lambda state: state.vscode)(self.sync)

    @mainthread
    def reset(self: SetupPage) -> None:
        self.stage = 0

    @mainthread
    def sync(self: SetupPage, state: VSCodeState) -> None:
        if state.status is None:
            self.is_installed = False
            self.url = ''
        else:
            self.is_installed = state.status.is_service_installed
            if state.status.name:
                self.url = f'{CODE_TUNNEL_URL_PREFIX}{state.status.name}'
            if self.stage == 0:
                self.stage = 1

    @mainthread
    def show_url(self: SetupPage) -> None:
        if self.url:
            self.stage = 2

    async def set_name(self: SetupPage) -> None:
        self.reset()
        try:
            hostname = socket.gethostname()
            self.process = await asyncio.create_subprocess_exec(
                CODE_BINARY_PATH.as_posix(),
                'tunnel',
                '--accept-server-license-terms',
                'rename',
                hostname,
            )
            await self.process.wait()
        except subprocess.CalledProcessError:
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='VSCode',
                        content='Failed to setup: renaming the tunnel',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
        finally:
            await check_status()

    async def install_service(self: SetupPage) -> None:
        self.reset()
        try:
            self.process = await asyncio.create_subprocess_exec(
                CODE_BINARY_PATH.as_posix(),
                'tunnel',
                '--accept-server-license-terms',
                'service',
                'install',
            )
            await self.process.wait()
        except subprocess.CalledProcessError:
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='VSCode',
                        content='Failed to setup: installing service',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
        finally:
            await check_status()

    async def uninstall_service(self: SetupPage) -> None:
        self.reset()
        try:
            self.process = await asyncio.create_subprocess_exec(
                CODE_BINARY_PATH.as_posix(),
                'tunnel',
                '--accept-server-license-terms',
                'service',
                'uninstall',
            )
            await self.process.wait()
        except subprocess.CalledProcessError:
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='VSCode',
                        content='Failed to setup: uninstalling service',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
        finally:
            await check_status()

    def on_close(self: SetupPage) -> None:
        self.process.kill() if self.process.returncode is None else None


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('setup_page.kv').resolve().as_posix(),
)
