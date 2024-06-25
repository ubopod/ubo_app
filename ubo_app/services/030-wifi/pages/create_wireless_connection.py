# ruff: noqa: D100, D101, D102, D103, D104, D105, D107, N999
from __future__ import annotations

import asyncio
import pathlib
from typing import TYPE_CHECKING, cast

from kivy.lang.builder import Builder
from kivy.properties import BooleanProperty
from str_to_bool import str_to_bool
from ubo_gui.constants import SUCCESS_COLOR
from ubo_gui.page import PageWidget
from wifi_manager import add_wireless_connection

from ubo_app.logging import logger
from ubo_app.store.core import CloseApplicationEvent
from ubo_app.store.main import dispatch
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.wifi import WiFiType, WiFiUpdateRequestAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.qrcode import qrcode_input

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item

# Regular expression pattern
# WIFI:S:<SSID>;T:<WEP|WPA|blank>;P:<PASSWORD>;H:<true|false|blank>;;
BARCODE_PATTERN = (
    r'^WIFI:S:(?P<SSID>[^;]*);(?:T:(?P<Type>(?i:WEP|WPA|WPA2|nopass));)'
    r'?(?:P:(?P<Password>[^;]*);)?(?:H:(?P<Hidden>(?i:true|false));)?;$|'
    r'^WIFI:T:(?P<Type_>(?i:WEP|WPA|WPA2|nopass));S:(?P<SSID_>[^;]*);'
    r'(?:P:(?P<Password_>[^;]*);)?(?:H:(?P<Hidden_>(?i:true|false|));)?;$'
)


class CreateWirelessConnectionPage(PageWidget):
    creating = BooleanProperty(defaultvalue=False)

    def __init__(
        self: CreateWirelessConnectionPage,
        items: Sequence[Item] | None = None,
        *args: object,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs, items=items)
        create_task(self.create_wireless_connection())

    async def create_wireless_connection(self: CreateWirelessConnectionPage) -> None:
        try:
            _, match = await qrcode_input(
                BARCODE_PATTERN,
                prompt='Scan WiFi QR-Code With Front Camera',
                extra_information='Go to your phone settings, choose {QR|K Y UW AA R} '
                'code and hold it in front of the camera to scan it',
            )
        except asyncio.CancelledError:
            dispatch(CloseApplicationEvent(application=self))
            return

        if not match:
            dispatch(CloseApplicationEvent(application=self))
            return
        ssid = match.get('SSID') or match.get('SSID_')
        if ssid is None:
            dispatch(CloseApplicationEvent(application=self))
            return

        password = match.get('Password') or match.get('Password_')
        type = cast(WiFiType, match.get('Type') or match.get('Type_'))
        hidden = (
            str_to_bool(match.get('Hidden') or match.get('Hidden_') or 'false') == 1
        )

        if not password:
            logger.warning('Password is required')
            dispatch(CloseApplicationEvent(application=self))
            return

        self.creating = True

        await add_wireless_connection(
            ssid=ssid,
            password=password,
            type=type or WiFiType.nopass,
            hidden=hidden,
        )

        logger.info(
            'Wireless connection created',
            extra={
                'ssid': ssid,
                'type': type,
                'hidden': hidden,
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
                    icon='󱛃',
                    chime=Chime.ADD,
                ),
            ),
            CloseApplicationEvent(application=self),
        )


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('create_wireless_connection.kv')
    .resolve()
    .as_posix(),
)
