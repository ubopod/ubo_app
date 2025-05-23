# ruff: noqa: D100, D101, D102, D103, D104, D105, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from constants import get_signal_icon
from debouncer import DebounceOptions, debounce
from kivy.clock import mainthread
from kivy.properties import StringProperty
from ubo_gui.menu.types import (
    ActionItem,
    HeadlessMenu,
    SubMenuItem,
)
from ubo_gui.prompt import PromptWidget
from wifi_manager import (
    connect_wireless_connection,
    disconnect_wireless_connection,
    forget_wireless_connection,
    get_active_connection_ssid,
    get_active_connection_state,
    get_wifi_device,
)

from ubo_app.store.core.types import CloseApplicationAction
from ubo_app.store.main import store
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiConnection,
    WiFiUpdateRequestAction,
)
from ubo_app.store.ubo_actions import UboApplicationItem, register_application
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import UboPromptWidget

from .create_wireless_connection import CreateWirelessConnectionPage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _WiFiConnectionPage(UboPromptWidget):
    ssid: str = StringProperty()
    state: ConnectionState = StringProperty(defaultvalue=ConnectionState.UNKNOWN)

    def first_option_callback(self) -> None:
        if self.state is ConnectionState.CONNECTED:
            create_task(disconnect_wireless_connection())
        elif self.state is ConnectionState.DISCONNECTED:
            create_task(connect_wireless_connection(self.ssid))
        store.dispatch(WiFiUpdateRequestAction(reset=True))

    def second_option_callback(self) -> None:
        create_task(forget_wireless_connection(self.ssid))
        store.dispatch(
            CloseApplicationAction(application_instance_id=self.id),
            WiFiUpdateRequestAction(reset=True),
        )

    def update(self, *_: tuple[Any, ...]) -> None:
        if self.state is ConnectionState.CONNECTED:
            self.first_option_label = 'Disconnect'
            self.first_option_icon = '󰖪'
            self.first_option_color = 'black'
            self.first_option_background_color = (
                PromptWidget.first_option_background_color.defaultvalue
            )
            self.icon = '󰖩'
        elif self.state is ConnectionState.DISCONNECTED:
            self.first_option_label = 'Connect'
            self.first_option_icon = '󰖩'
            self.first_option_color = 'black'
            self.first_option_background_color = (
                PromptWidget.first_option_background_color.defaultvalue
            )
            self.icon = '󰖪'
        elif self.state is ConnectionState.CONNECTING:
            self.first_option_label = 'Connecting...'
            self.first_option_icon = ''
            self.first_option_color = 'white'
            self.first_option_background_color = 'black'
            self.icon = ''
        elif self.state is ConnectionState.UNKNOWN:
            self.first_option_label = ''
            self.first_option_icon = ''
            self.first_option_color = 'white'
            self.first_option_background_color = 'black'
            self.icon = ''

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs, items=None)
        self.title = None
        self.prompt = f'SSID: {self.ssid}'
        self.first_option_is_short = False
        self.second_option_label = 'Delete'
        self.second_option_icon = '󰆴'
        self.second_option_is_short = False

        self.bind(state=self.update)
        self.update()

        @debounce(
            wait=0.5,
            options=DebounceOptions(leading=False, trailing=True, time_window=0.5),
        )
        async def update_status() -> None:
            if await get_active_connection_ssid() == self.ssid:
                state = await get_active_connection_state()
            else:
                state = ConnectionState.DISCONNECTED
            mainthread(lambda: setattr(self, 'state', state))()

        create_task(update_status())

        async def listener() -> None:
            wifi_device = await get_wifi_device()
            if not wifi_device:
                return

            async for _ in wifi_device.properties_changed:
                create_task(update_status())

        create_task(listener())


register_application(
    application=_WiFiConnectionPage,
    application_id='wifi:connection-page',
)
register_application(
    application=CreateWirelessConnectionPage,
    application_id='wifi:create-connection-page',
)


@store.autorun(lambda state: state.wifi.connections)
def wireless_connections_menu(
    connections: Sequence[WiFiConnection] | None,
) -> HeadlessMenu:
    if connections is None:
        return HeadlessMenu(
            title='Wi-Fi',
            items=[],
            placeholder='Loading...',
        )

    icons = {
        ConnectionState.CONNECTED: '󱚽',
        ConnectionState.DISCONNECTED: '󱛅',
        ConnectionState.CONNECTING: '󱛇',
        ConnectionState.UNKNOWN: '󱚵',
    }
    items = (
        [
            UboApplicationItem(
                key=connection.ssid,
                label=connection.ssid,
                application_id='wifi:connection-page',
                icon=get_signal_icon(connection.signal_strength)
                if connection.state == ConnectionState.DISCONNECTED
                else icons[connection.state],
                initialization_kwargs={
                    'ssid': connection.ssid,
                },
            )
            for connection in connections
        ]
        if connections is not None
        else []
    )

    placeholder = 'Loading...' if connections is None else 'No Wi-Fi connections found'

    return HeadlessMenu(
        title='Wi-Fi',
        items=items,
        placeholder=placeholder,
    )


def list_connections() -> Callable[[], HeadlessMenu]:
    store.dispatch(WiFiUpdateRequestAction())
    return wireless_connections_menu


WiFiMainMenu = SubMenuItem(
    label='WiFi',
    icon='󰖩',
    sub_menu=HeadlessMenu(
        title='WiFi Settings',
        items=[
            UboApplicationItem(
                label='Add',
                icon='󱛃',
                application_id='wifi:create-connection-page',
            ),
            ActionItem(
                label='Select',
                icon='󱖫',
                action=list_connections,
            ),
        ],
    ),
)
