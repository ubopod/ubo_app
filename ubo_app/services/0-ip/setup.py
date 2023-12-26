# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from collections import defaultdict
from socket import AddressFamily
from typing import cast

import psutil
from reducer import IPState
from ubo_gui.menu.types import ActionItem, HeadlessMenu, SubMenuItem

from ubo_app.store import autorun, dispatch
from ubo_app.store.app import RegisterSettingAppAction
from ubo_app.store.status_icons import StatusIconsRegisterAction


@autorun(lambda state: cast(IPState, getattr(state, 'ip', None)))
def get_ip_addresses(selector_result: IPState) -> list[SubMenuItem]:
    ip_addresses_by_interface = defaultdict(list)
    for interface_name, interface_addresses in psutil.net_if_addrs().items():
        for address in interface_addresses:
            if address.family == AddressFamily.AF_INET:
                ip_addresses_by_interface[interface_name].append(address.address)
    return [
        SubMenuItem(
            label=interface_name,
            icon='cable'
            if interface_name.startswith('eth')
            else 'wifi'
            if interface_name.startswith('wlan')
            else 'computer'
            if interface_name.startswith('lo')
            else 'network_node',
            sub_menu=HeadlessMenu(
                title=f'IP Addresses - {interface_name}',
                items=[
                    ActionItem(label=ip_address, icon='lan', action=print)
                    for ip_address in ip_addresses
                ],
            ),
        )
        for interface_name, ip_addresses in ip_addresses_by_interface.items()
    ]


IPMainMenu = SubMenuItem(
    label='IP Addresses',
    icon='lan',
    sub_menu=HeadlessMenu(
        title='WiFi Settings',
        items=get_ip_addresses,
    ),
)


def init_service() -> None:
    dispatch(
        [
            RegisterSettingAppAction(
                menu_item=IPMainMenu,
            ),
            StatusIconsRegisterAction(
                icon='public',
                priority=-1,
            ),
        ],
    )
