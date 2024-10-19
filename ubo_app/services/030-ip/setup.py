# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import socket
from collections import defaultdict
from typing import TYPE_CHECKING

import psutil
from constants import INTERNET_STATE_ICON_ID, INTERNET_STATE_ICON_PRIORITY
from ubo_gui.constants import DANGER_COLOR
from ubo_gui.menu.types import HeadlessMenu, Item, SubMenuItem

from ubo_app.store.core import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.ethernet import NetState
from ubo_app.store.services.ip import (
    IpNetworkInterface,
    IpSetIsConnectedAction,
    IpUpdateInterfacesAction,
)
from ubo_app.store.status_icons import StatusIconsRegisterAction
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Sequence


@store.autorun(lambda state: state.ip.interfaces)
def get_ip_addresses(interfaces: Sequence[IpNetworkInterface]) -> list[SubMenuItem]:
    if not interfaces:
        return []
    return [
        SubMenuItem(
            label=interface.name,
            icon='󰈀'
            if interface.name.startswith('eth')
            else ''
            if interface.name.startswith('wlan')
            else '󰕇'
            if interface.name.startswith('lo')
            else '󰛳',
            sub_menu=HeadlessMenu(
                title=f'󰩟{interface.name}',
                items=[
                    Item(
                        label=ip_address,
                        icon='󰩠',
                    )
                    for ip_address in interface.ip_addresses
                ],
                placeholder='No IP addresses',
            ),
        )
        for interface in interfaces
    ]


def load_ip_addresses() -> None:
    ip_addresses_by_interface = defaultdict(list)
    for interface_name, ip_addresses in psutil.net_if_addrs().items():
        for address in ip_addresses:
            if address.family == socket.AddressFamily.AF_INET:
                ip_addresses_by_interface[interface_name].append(address.address)

    store.dispatch(
        IpUpdateInterfacesAction(
            interfaces=[
                IpNetworkInterface(name=interface_name, ip_addresses=ip_addresses)
                for interface_name, ip_addresses in ip_addresses_by_interface.items()
            ],
        ),
    )


async def check_connection() -> bool:
    while True:
        load_ip_addresses()
        if await send_command('connection', has_output=True) == NetState.CONNECTED:
            store.dispatch(
                StatusIconsRegisterAction(
                    icon='󰖟',
                    priority=INTERNET_STATE_ICON_PRIORITY,
                    id=INTERNET_STATE_ICON_ID,
                ),
                IpSetIsConnectedAction(is_connected=True),
            )
        else:
            store.dispatch(
                StatusIconsRegisterAction(
                    icon=f'[color={DANGER_COLOR}]󰪎[/color]',
                    priority=INTERNET_STATE_ICON_PRIORITY,
                    id=INTERNET_STATE_ICON_ID,
                ),
                IpSetIsConnectedAction(is_connected=False),
            )
        await asyncio.sleep(1)


IpMainMenu = SubMenuItem(
    label='IP Addresses',
    icon='󰩟',
    sub_menu=HeadlessMenu(
        title='󰩟IP Addresses',
        items=get_ip_addresses,
        placeholder='No IP addresses',
    ),
)


async def init_service() -> None:
    store.dispatch(
        RegisterSettingAppAction(
            priority=0,
            category=SettingsCategory.NETWORK,
            menu_item=IpMainMenu,
        ),
    )

    await check_connection()
