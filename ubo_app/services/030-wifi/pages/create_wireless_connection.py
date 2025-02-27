# ruff: noqa: D100, D101, D102, D103, D104, D105, D107, N999
from __future__ import annotations

import asyncio
import pathlib
from typing import TYPE_CHECKING, cast

from kivy.lang.builder import Builder
from kivy.properties import BooleanProperty
from str_to_bool import str_to_bool
from ubo_gui.constants import SUCCESS_COLOR, WARNING_COLOR
from ubo_gui.page import PageWidget
from wifi_manager import add_wireless_connection

from ubo_app.logger import logger
from ubo_app.store.core.types import CloseApplicationAction
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    InputMethod,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.store.services.voice import ReadableInformation
from ubo_app.store.services.wifi import WiFiType, WiFiUpdateRequestAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_gui.menu.types import Item

# Regular expression pattern
# WIFI:S:<SSID>;T:<WEP|WPA|blank>;P:<PASSWORD>;H:<true|false|blank>;;
BARCODE_PATTERN = (
    r'^WIFI:S:(?P<SSID>[^;]*);(?:T:(?P<Type>(?i:WEP|WPA|WPA2|nopass));)'
    r'?(?:P:(?P<Password>[^;]*);)?(?:H:(?P<Hidden>(?i:true|false));)?;$|'
    r'^WIFI:T:(?P<Type_>(?i:WEP|WPA|WPA2|nopass));S:(?P<SSID_>[^;]*);'
    r'(?:P:(?P<Password_>[^;]*);)?(?:H:(?P<Hidden_>(?i:true|false|));)?;$'
)
HOTSPOT_GRACE_TIME = 5


async def input_wifi_connection(
    *,
    input_methods: InputMethod = InputMethod.WEB_DASHBOARD,
    on_creating: Callable[[], None] | None = None,
) -> None:
    """Input WiFi connection."""
    logger.debug('wifi connection input - start')
    try:
        _, result = await ubo_input(
            input_methods=input_methods,
            prompt='Enter WiFi connection',
            qr_code_generation_instructions=ReadableInformation(
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
        logger.debug('wifi connection input - cancelled')
        return

    logger.debug('wifi connection input - result', extra={'result': result})

    if not result:
        logger.debug('wifi connection input - no result')
        return
    ssid = result.data.get('SSID') or result.data.get('SSID_')
    if ssid is None:
        logger.debug('wifi connection input - no ssid')
        return

    password = result.data.get('Password') or result.data.get('Password_')
    type = result.data.get('Type') or result.data.get('Type_')
    if type:
        type = type.upper()
    type = cast(WiFiType, type)
    hidden = (
        str_to_bool(
            result.data.get('Hidden') or result.data.get('Hidden_') or 'false',
        )
        == 1
    )

    if not password:
        logger.debug('wifi connection input - no password')
        logger.warning('Password is required')
        return

    if on_creating:
        on_creating()

    if result.method is InputMethod.WEB_DASHBOARD:
        logger.debug(
            'wifi connection input - waiting for hotspot to go down',
            extra={'grace time': HOTSPOT_GRACE_TIME},
        )
        # Wait for hotspot to go down
        notification = Notification(
            id='wifi-wait-hotspot',
            title='Please wait!',
            content='To avoid interference we need to wait for the hotspot to go down.',
            display_type=NotificationDisplayType.STICKY,
            color=WARNING_COLOR,
            icon='󱋆',
        )
        store.dispatch(
            NotificationsAddAction(
                notification=notification,
            ),
        )
        await asyncio.sleep(HOTSPOT_GRACE_TIME)
        store.dispatch(NotificationsClearByIdAction(id='wifi-wait-hotspot'))
        logger.debug(
            'wifi connection input - done waiting for hotspot to go down',
            extra={'grace time': HOTSPOT_GRACE_TIME},
        )

    logger.debug('wifi connection input - creating connection')
    try:
        await add_wireless_connection(
            ssid=ssid,
            password=password,
            type=type or WiFiType.NOPASS,
            hidden=hidden,
        )
    except Exception:
        logger.exception('wifi connection input - error while creating connection')
        return

    logger.info(
        'Wireless connection created',
        extra={
            'ssid': ssid,
            'password': '<HIDDEN>' if password else '<NOT PROVIDED>',
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
                    ssid
                }" was added successfully""",
                display_type=NotificationDisplayType.FLASH,
                color=SUCCESS_COLOR,
                icon='󱛃',
                chime=Chime.ADD,
            ),
        ),
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
        await input_wifi_connection(
            on_creating=lambda: setattr(self, 'creating', True),
            input_methods=InputMethod.ALL,
        )
        store.dispatch(CloseApplicationAction(application=self))


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('create_wireless_connection.kv')
    .resolve()
    .as_posix(),
)
