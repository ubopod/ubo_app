# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import socket
from collections import defaultdict
from typing import Sequence

import psutil
from constants import INTERNET_STATE_ICON_ID, INTERNET_STATE_ICON_PRIORITY
from ubo_gui.menu.types import ActionItem, HeadlessMenu, SubMenuItem

from ubo_app.store import autorun, dispatch, subscribe_event
from ubo_app.store.main import RegisterSettingAppAction
from ubo_app.store.services.ip import (
    IpNetworkInterface,
    IpUpdateAction,
    IpUpdateRequestAction,
    IpUpdateRequestEvent,
)
from ubo_app.store.status_icons import StatusIconsRegisterAction
from ubo_app.utils.async_ import create_task


@autorun(lambda state: state.ip.interfaces)
def get_ip_addresses(interfaces: Sequence[IpNetworkInterface]) -> list[SubMenuItem]:
    if not interfaces:
        return []
    return [
        SubMenuItem(
            label=interface.name,
            icon='cable'
            if interface.name.startswith('eth')
            else 'wifi'
            if interface.name.startswith('wlan')
            else 'computer'
            if interface.name.startswith('lo')
            else 'network_node',
            sub_menu=HeadlessMenu(
                title=f'IP Addresses - {interface.name}',
                items=[
                    ActionItem(
                        label=ip_address,
                        icon='lan',
                        action=lambda: None,
                    )
                    for ip_address in interface.ip_addresses
                ],
            ),
        )
        for interface in interfaces
    ]


def load_ip_addresses(_: IpUpdateRequestEvent | None = None) -> None:
    ip_addresses_by_interface = defaultdict(list)
    for interface_name, ip_addresses in psutil.net_if_addrs().items():
        for address in ip_addresses:
            if address.family == socket.AddressFamily.AF_INET:
                ip_addresses_by_interface[interface_name].append(address.address)

    dispatch(
        IpUpdateAction(
            interfaces=[
                IpNetworkInterface(name=interface_name, ip_addresses=ip_addresses)
                for interface_name, ip_addresses in ip_addresses_by_interface.items()
            ],
        ),
    )


def is_connected() -> bool:
    try:
        with socket.create_connection(('1.1.1.1', 53), timeout=2):
            return True
    except OSError:
        return False


async def check_connection() -> bool:
    while True:
        await asyncio.sleep(1)
        if is_connected():
            dispatch(
                IpUpdateRequestAction(),
                StatusIconsRegisterAction(
                    icon='public',
                    priority=INTERNET_STATE_ICON_PRIORITY,
                    id=INTERNET_STATE_ICON_ID,
                ),
            )
        else:
            dispatch(
                IpUpdateRequestAction(),
                StatusIconsRegisterAction(
                    icon='public_off',
                    priority=INTERNET_STATE_ICON_PRIORITY,
                    id=INTERNET_STATE_ICON_ID,
                ),
            )


IpMainMenu = SubMenuItem(
    label='IP Addresses',
    icon='lan',
    sub_menu=HeadlessMenu(
        title='IP Addresses',
        items=get_ip_addresses,
    ),
)


def init_service() -> None:
    dispatch(RegisterSettingAppAction(menu_item=IpMainMenu))
    create_task(check_connection())

    subscribe_event(
        IpUpdateRequestEvent,
        load_ip_addresses,
    )
    load_ip_addresses()
