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
from ubo_app.store.core import CloseApplicationAction
from ubo_app.store.main import store
from ubo_app.store.operations import InputFieldDescription, InputFieldType
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationExtraInformation,
    NotificationsAddAction,
)
from ubo_app.store.services.wifi import WiFiType, WiFiUpdateRequestAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input

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
            _, data = await ubo_input(
                prompt='Enter WiFi connection',
                extra_information=NotificationExtraInformation(
                    text='Go to your phone settings, choose QR code and hold it in '
                    'front of the camera to scan it.',
                    picovoice_text='Go to your phone settings, choose {QR|K Y UW AA R} '
                    'code and hold it in front of the camera to scan it.',
                ),
                pattern=BARCODE_PATTERN,
                fields=[
                    InputFieldDescription(
                        name='SSID',
                        label='SSID',
                        type=InputFieldType.TEXT,
                        description='The name of the WiFi network',
                        required=True,
                    ),
                    InputFieldDescription(
                        name='Password',
                        label='Password',
                        type=InputFieldType.PASSWORD,
                        description='The password of the WiFi network',
                        required=False,
                    ),
                    InputFieldDescription(
                        name='Type',
                        label='Type',
                        type=InputFieldType.SELECT,
                        description='The type of the WiFi network',
                        default='WPA2',
                        options=['WEP', 'WPA', 'WPA2', 'nopass'],
                        required=False,
                    ),
                    InputFieldDescription(
                        name='Hidden',
                        label='Hidden',
                        type=InputFieldType.CHECKBOX,
                        description='Is the WiFi network hidden?',
                        default='false',
                        required=False,
                    ),
                ],
            )
        except asyncio.CancelledError:
            store.dispatch(CloseApplicationAction(application=self))
            return

        if not data:
            store.dispatch(CloseApplicationAction(application=self))
            return
        ssid = data.get('SSID') or data.get('SSID_')
        if ssid is None:
            store.dispatch(CloseApplicationAction(application=self))
            return

        password = data.get('Password') or data.get('Password_')
        type = data.get('Type') or data.get('Type_')
        if type:
            type = type.upper()
        type = cast(WiFiType, type)
        hidden = str_to_bool(data.get('Hidden') or data.get('Hidden_') or 'false') == 1

        if not password:
            logger.warning('Password is required')
            store.dispatch(CloseApplicationAction(application=self))
            return

        self.creating = True

        await add_wireless_connection(
            ssid=ssid,
            password=password,
            type=type or WiFiType.NOPASS,
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

        store.dispatch(
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
            CloseApplicationAction(application=self),
        )


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('create_wireless_connection.kv')
    .resolve()
    .as_posix(),
)
