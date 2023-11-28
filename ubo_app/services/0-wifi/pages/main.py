# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import Sequence, cast

from __ubo_service__.wifi_manager import wifi_manager
from ubo_gui.menu.types import (
    ApplicationItem,
    HeadlessMenu,
    Item,
    SubMenuItem,
)
from ubo_gui.prompt import PromptWidget

from ubo_app.logging import logger
from ubo_app.store import autorun, dispatch
from ubo_app.store.wifi import WiFiState, WiFiUpdateEvent

from .setup import WiFiSetupPage


class WiFiNetworkPage(PromptWidget):
    ssid: str

    def first_option_callback(self: WiFiNetworkPage) -> None:
        current = wifi_manager.get_current_network()
        if current:
            current_ssid, network_id = current
            if current_ssid == self.ssid:
                wifi_manager.disable_network(network_id)
                self.update()
                return

        network_ids = wifi_manager.get_network_id(self.ssid)
        if network_ids:
            wifi_manager.connect_to_wifi(network_ids[0])
            self.update()

    def second_option_callback(self: WiFiNetworkPage) -> None:
        wifi_manager.forget_wifi(self.ssid)
        self.on_close()
        dispatch(WiFiUpdateEvent())

    def update(self: WiFiNetworkPage) -> None:
        current = wifi_manager.get_current_network()
        self.prompt = f'SSID: {self.ssid}'
        if current:
            current_ssid, _ = current
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
        self.update()


@autorun(lambda state: cast(WiFiState, getattr(state, 'wi_fi', None)))
def network_items(selector_result: WiFiState) -> Sequence[Item]:
    if not selector_result:
        return []

    wifi_state = selector_result

    def wi_fi_network_creator(ssid: str) -> type[WiFiNetworkPage]:
        class WiFiNetworkPageWithSSID(WiFiNetworkPage):
            def __init__(self: WiFiNetworkPageWithSSID, **kwargs: object) -> None:
                self.ssid = ssid
                super().__init__(**kwargs)

        return WiFiNetworkPageWithSSID

    return [
        ApplicationItem(
            label=connection.ssid,
            application=wi_fi_network_creator(connection.ssid),
        )
        for connection in wifi_state.connections
    ]


WiFiMainMenu = SubMenuItem(
    label='WiFi',
    icon='wifi',
    sub_menu=HeadlessMenu(
        title='WiFi Settings',
        items=[
            ApplicationItem(
                label='Add',
                icon='add',
                application=WiFiSetupPage,
            ),
            SubMenuItem(
                label='Select',
                icon='list',
                sub_menu=HeadlessMenu(
                    title='Wi-Fi Connections',
                    items=network_items,
                ),
            ),
        ],
    ),
)
