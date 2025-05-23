# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import pathlib
import re
import subprocess

from commands import check_status
from kivy.clock import mainthread
from kivy.lang.builder import Builder
from kivy.properties import NumericProperty, StringProperty

from ubo_app.colors import DANGER_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import CloseApplicationAction
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.rpi_connect import RPiConnectLoginEvent
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import UboPageWidget


class SignInPage(UboPageWidget):
    stage: int = NumericProperty(0)
    url: str | None = StringProperty()

    def __init__(
        self: SignInPage,
        *args: object,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs, items=[])
        store.subscribe_event(
            RPiConnectLoginEvent,
            lambda: store.dispatch(
                CloseApplicationAction(application_instance_id=self.id),
            ),
        )
        create_task(self.login())

    async def login(self: SignInPage) -> None:
        try:
            self.process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'rpi-connect',
                'signin',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if self.process.stdout is None:
                return
            output = (await self.process.stdout.readline()).decode()
            regex = r'^Complete sign in by visiting (?P<url>[^\n]*)'
            match = re.search(regex, output)
            if match:

                def set_properties() -> None:
                    self.url = match.group('url')
                    self.stage = 1

                mainthread(set_properties)()
                await self.process.wait()
            else:
                logger.error(
                    'RPi Connect: Failed to login: invalid output',
                    extra={'output': output},
                )
                store.dispatch(
                    NotificationsAddAction(
                        notification=Notification(
                            title='RPi-Connect',
                            content='Failed to login: invalid output',
                            display_type=NotificationDisplayType.STICKY,
                            color=DANGER_COLOR,
                            icon='󰜺',
                            chime=Chime.FAILURE,
                        ),
                    ),
                )
        except subprocess.CalledProcessError:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='RPi-Connect',
                        content='Failed to login: process error',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
            raise
        finally:
            await check_status()

    def on_close(self: SignInPage) -> None:
        self.process.kill() if self.process.returncode is None else None


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('sign_in_page.kv').resolve().as_posix(),
)
