# ruff: noqa: D100, D101, D102, D103, D104, D105, D107, N999
from __future__ import annotations

from typing import Any, Sequence

from constants import get_signal_icon
from debouncer import DebounceOptions, debounce
from kivy.properties import BooleanProperty
from ubo_gui.menu.types import (
    ActionItem,
    ApplicationItem,
    HeadlessMenu,
    Item,
    SubMenuItem,
)
from ubo_gui.prompt import PromptWidget
from wifi_manager import (
    connect_wireless_connection,
    disconnect_wireless_connection,
    forget_wireless_connection,
    get_active_connection_ssid,
    get_wifi_device,
)

from ubo_app.store import autorun, dispatch
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiState,
    WiFiUpdateRequestAction,
)
from ubo_app.utils.async_ import create_task

from .create_wireless_connection import CreateWirelessConnectionPage


class WiFiConnectionPage(PromptWidget):
    ssid: str
    is_active = BooleanProperty(defaultvalue=None)

    def first_option_callback(self: WiFiConnectionPage) -> None:
        if self.is_active:
            create_task(disconnect_wireless_connection())
        else:
            create_task(connect_wireless_connection(self.ssid))
        dispatch(
            WiFiUpdateRequestAction(
                reset=True,
            ),
        )

    def second_option_callback(self: WiFiConnectionPage) -> None:
        create_task(forget_wireless_connection(self.ssid))
        self.dispatch('on_close')
        dispatch(
            WiFiUpdateRequestAction(reset=True),
        )

    def update(self: WiFiConnectionPage, *_: tuple[Any, ...]) -> None:
        self.first_option_background_color = (
            PromptWidget.first_option_background_color.defaultvalue
        )
        if self.is_active:
            self.first_option_label = 'Disconnect'
            self.first_option_icon = '󰖪'
            self.icon = '󰖩'
        else:
            self.first_option_label = 'Connect'
            self.first_option_icon = '󰖩'
            self.icon = '󰖪'

    def __init__(self: WiFiConnectionPage, **kwargs: object) -> None:
        super().__init__(**kwargs, items=None)
        self.prompt = f'SSID: {self.ssid}'
        self.icon = ''
        self.first_option_background_color = 'black'
        self.first_option_label = ''
        self.first_option_is_short = False
        self.second_option_label = 'Delete'
        self.second_option_icon = '󰆴'
        self.second_option_is_short = False

        self.bind(is_active=self.update)

        @debounce(
            wait=0.5,
            options=DebounceOptions(leading=False, trailing=True, time_window=2),
        )
        async def update_status() -> None:
            self.is_active = await get_active_connection_ssid() == self.ssid

        create_task(update_status())

        async def listener() -> None:
            wifi_device = await get_wifi_device()
            if not wifi_device:
                return

            async for _ in wifi_device.properties_changed:
                create_task(update_status())

        create_task(listener())


@autorun(lambda state: state.wifi)
def wireless_connection_items(wifi_state: WiFiState) -> Sequence[Item]:
    if not wifi_state:
        return []

    def wifi_network_creator(ssid: str) -> type[WiFiConnectionPage]:
        class WiFiNetworkPageWithSSID(WiFiConnectionPage):
            def __init__(self: WiFiNetworkPageWithSSID, **kwargs: object) -> None:
                self.ssid = ssid
                self.title = None
                super().__init__(**kwargs)

        return WiFiNetworkPageWithSSID

    icons = {
        ConnectionState.CONNECTED: '󱚽',
        ConnectionState.DISCONNECTED: '󱛅',
        ConnectionState.CONNECTING: '󱛇',
        ConnectionState.UNKNOWN: '󱚵',
    }
    return (
        [
            ApplicationItem(
                label=connection.ssid,
                application=wifi_network_creator(connection.ssid),
                icon=get_signal_icon(connection.signal_strength)
                if connection.state == ConnectionState.DISCONNECTED
                else icons[connection.state],
            )
            for connection in wifi_state.connections
        ]
        if wifi_state.connections is not None
        else [Item(label='Loading...')]
    )


def list_connections() -> HeadlessMenu:
    dispatch(WiFiUpdateRequestAction())
    return HeadlessMenu(
        title='Wi-Fi',
        items=wireless_connection_items,
        placeholder='No Wi-Fi connections found',
    )


WiFiMainMenu = SubMenuItem(
    label='WiFi',
    icon='󰖩',
    sub_menu=HeadlessMenu(
        title='WiFi Settings',
        items=[
            ApplicationItem(
                label='Add',
                icon='󱛃',
                application=CreateWirelessConnectionPage,
            ),
            ActionItem(
                label='Select',
                icon='󱖫',
                action=list_connections,
            ),
        ],
    ),
)
