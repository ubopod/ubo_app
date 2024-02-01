# ruff: noqa: D100, D101, D102, D103, D104, D105, D107, N999
from __future__ import annotations

import pathlib
from typing import Sequence

from kivy.app import Builder
from kivy.clock import Clock
from kivy.properties import BooleanProperty
from ubo_gui.constants import SUCCESS_COLOR
from ubo_gui.menu.types import ActionItem, Item
from ubo_gui.page import PageWidget
from wifi_manager import add_wireless_connection

from ubo_app.logging import logger
from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.services.camera import CameraStartViewfinderAction
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.sound import SoundPlayChimeAction
from ubo_app.store.services.wifi import (
    WiFiCreateEvent,
    WiFiType,
    WiFiUpdateRequestAction,
)
from ubo_app.utils.async_ import create_task

# Regular expression pattern
# WIFI:S:<SSID>;T:<WEP|WPA|blank>;P:<PASSWORD>;H:<true|false|blank>;;
barcode_pattern = r"""WIFI:S:(?P<SSID>[^;]*);(?:T:(?P<Type>(?i:WEP|WPA|WPA2|nopass));)\
?(?:P:(?P<Password>[^;]*);)?(?:H:(?P<Hidden>(?i:true|false));)?"""


class CreateWirelessConnectionPage(PageWidget):
    creating = BooleanProperty(defaultvalue=False)

    def __init__(
        self: CreateWirelessConnectionPage,
        items: Sequence[Item] | None = None,
        *args: object,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs, items=items)
        self.unsubscribe = subscribe_event(
            WiFiCreateEvent,
            self.create_wireless_connection,
        )
        dispatch(SoundPlayChimeAction(name='scan'))

    def create_wireless_connection(
        self: CreateWirelessConnectionPage,
        event: WiFiCreateEvent,
    ) -> None:
        connection = event.connection
        ssid = connection.ssid
        password = connection.password

        if not password:
            logger.warn('Password is required')
            return

        async def act() -> None:
            await add_wireless_connection(
                ssid=ssid,
                password=password,
                type=connection.type or WiFiType.nopass,
                hidden=connection.hidden,
            )

            logger.info(
                'Wireless connection created',
                extra={
                    'ssid': ssid,
                    'type': connection.type,
                    'hidden': connection.hidden,
                },
            )

            dispatch(
                WiFiUpdateRequestAction(reset=True),
                NotificationsAddAction(
                    notification=Notification(
                        title=f'"{ssid}" Added',
                        content=f"""WiFi connection with ssid "{
                        ssid}" was added successfully""",
                        display_type=NotificationDisplayType.FLASH,
                        color=SUCCESS_COLOR,
                        icon='wifi_add',
                        chime=Chime.ADD,
                    ),
                ),
            )
            self.dispatch('on_close')

        self.creating = True
        create_task(act())

    def on_close(self: CreateWirelessConnectionPage) -> None:
        self.unsubscribe()
        return super().on_close()

    def get_item(self: CreateWirelessConnectionPage, index: int) -> ActionItem | None:
        if index == 2:  # noqa: PLR2004
            return ActionItem(
                label='start',
                is_short=True,
                icon='camera',
                action=lambda: dispatch(
                    CameraStartViewfinderAction(barcode_pattern=barcode_pattern),
                ),
            )
        return super().get_item(index)


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('create_wireless_connection.kv')
    .resolve()
    .as_posix(),
)
