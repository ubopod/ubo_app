# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import math
from typing import Sequence, cast

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
    get_active_ssid,
)

from ubo_app.logging import logger
from ubo_app.store import autorun, dispatch
from ubo_app.store.wifi import (
    WiFiState,
    WiFiUpdateRequestAction,
    WiFiUpdateRequestActionPayload,
)
from ubo_app.utils.async_ import create_task

from .create_wireless_connection import CreateWirelessConnectionPage


class WiFiNetworkPage(PromptWidget):
    ssid: str

    def first_option_callback(self: WiFiNetworkPage) -> None:
        async def act() -> None:
            current_ssid = await get_active_ssid()
            if current_ssid and current_ssid == self.ssid:
                await disconnect_wireless_connection()
            else:
                await connect_wireless_connection(self.ssid)
            dispatch(
                WiFiUpdateRequestAction(
                    payload=WiFiUpdateRequestActionPayload(reset=True),
                ),
            )
            await self.update()

        create_task(act())

    def second_option_callback(self: WiFiNetworkPage) -> None:
        create_task(forget_wireless_connection(self.ssid))
        self.dispatch('on_close')
        dispatch(
            WiFiUpdateRequestAction(payload=WiFiUpdateRequestActionPayload(reset=True)),
        )

    async def update(self: WiFiNetworkPage) -> None:
        self.prompt = f'SSID: {self.ssid}'

        current_ssid = await get_active_ssid()
        logger.info(
            'Checking ssids for this connection',
            extra={'current_ssid': current_ssid, 'self.ssid': self.ssid},
        )
        if current_ssid == self.ssid:
            self.first_option_label = 'Disconnect'
            self.first_option_icon = 'link_off'
            self.icon = 'wifi'
        else:
            self.first_option_label = 'Connect'
            self.first_option_icon = 'link'
            self.icon = 'wifi_off'

    def __init__(self: WiFiNetworkPage, **kwargs: object) -> None:
        super().__init__(**kwargs, items=None)
        self.first_option_is_short = False
        self.second_option_label = 'Delete'
        self.second_option_icon = 'delete'
        self.second_option_is_short = False
        create_task(self.update())


@autorun(lambda state: cast(WiFiState, getattr(state, 'wifi', None)))
def wireless_connection_items(selector_result: WiFiState) -> Sequence[Item]:
    if not selector_result:
        return []

    wifi_state = selector_result

    def wifi_network_creator(ssid: str) -> type[WiFiNetworkPage]:
        class WiFiNetworkPageWithSSID(WiFiNetworkPage):
            def __init__(self: WiFiNetworkPageWithSSID, **kwargs: object) -> None:
                self.ssid = ssid
                super().__init__(**kwargs)

        return WiFiNetworkPageWithSSID

    icons = [
        'signal_wifi_0_bar',
        'network_wifi_1_bar',
        'network_wifi_2_bar',
        'network_wifi_3_bar',
        'signal_wifi_4_bar',
    ]
    return (
        [
            ApplicationItem(
                label=connection.ssid,
                application=wifi_network_creator(connection.ssid),
                icon='link'
                if connection.is_active
                else icons[math.floor(connection.signal_strength / 100 * 4.999)],
            )
            for connection in wifi_state.connections
        ]
        if wifi_state.connections is not None
        else [ActionItem(label='Loading...', action=lambda: None)]
    )


def list_connections() -> HeadlessMenu:
    dispatch(WiFiUpdateRequestAction())
    return HeadlessMenu(
        title='Wi-Fi Connections',
        items=wireless_connection_items,
    )


WiFiMainMenu = SubMenuItem(
    label='WiFi',
    icon='wifi',
    sub_menu=HeadlessMenu(
        title='WiFi Settings',
        items=[
            ApplicationItem(
                label='Add',
                icon='add',
                application=CreateWirelessConnectionPage,
            ),
            ActionItem(
                label='Select',
                icon='list',
                action=list_connections,
            ),
        ],
    ),
)
