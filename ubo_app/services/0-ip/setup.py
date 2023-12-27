# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
from collections import defaultdict
from socket import AddressFamily
from typing import cast

import psutil
from constants import INTERNET_STATE_ICON_ID, INTERNET_STATE_ICON_PRIORITY
from pythonping import ping
from reducer import IPState
from ubo_gui.menu.types import ActionItem, HeadlessMenu, SubMenuItem

from ubo_app.store import autorun, dispatch
from ubo_app.store.app import RegisterSettingAppAction
from ubo_app.store.status_icons import StatusIconsRegisterAction
from ubo_app.utils.async_ import create_task


@autorun(lambda state: cast(IPState, getattr(state, 'ip', None)))
def get_ip_addresses(_: IPState) -> list[SubMenuItem]:
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


def is_connected() -> bool:
    try:
        response = ping('1.1.1.1', count=1, timeout=1)
        return response.success()
    except OSError:
        return False


async def check_connection() -> bool:
    while True:
        await asyncio.sleep(1)
        if is_connected():
            dispatch(
                StatusIconsRegisterAction(
                    icon='public',
                    priority=INTERNET_STATE_ICON_PRIORITY,
                    id=INTERNET_STATE_ICON_ID,
                ),
            )
        else:
            dispatch(
                StatusIconsRegisterAction(
                    icon='public_off',
                    priority=INTERNET_STATE_ICON_PRIORITY,
                    id=INTERNET_STATE_ICON_ID,
                ),
            )


create_task(check_connection())


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
        ],
    )
