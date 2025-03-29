# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import socket
import subprocess
from collections import defaultdict
from typing import TYPE_CHECKING

import psutil
from constants import INTERNET_STATE_ICON_ID, INTERNET_STATE_ICON_PRIORITY
from ubo_gui.menu.types import HeadlessMenu, Item, SubMenuItem

from ubo_app.colors import DANGER_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.ip import (
    IpNetworkInterface,
    IpSetIsConnectedAction,
    IpUpdateInterfacesAction,
)
from ubo_app.store.status_icons.types import StatusIconsRegisterAction
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.utils.types import Subscriptions


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


def load_network_interfaces() -> None:
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


async def monitor_interfaces(end_event: asyncio.Event) -> None:
    while not end_event.is_set():
        try:
            load_network_interfaces()
        except Exception:
            logger.exception('Failed to load network interfaces')
        finally:
            await asyncio.sleep(1)


async def monitor_connections(end_event: asyncio.Event) -> None:
    process = await asyncio.create_subprocess_exec(
        '/usr/bin/env',
        'ping',
        '8.8.8.8',
        '-s',
        '0',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if process.stdout:
        async for line in process.stdout:
            if end_event.is_set():
                process.kill()
                break
            if line.startswith(b'8 bytes from'):
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


async def init_service() -> Subscriptions:
    store.dispatch(
        RegisterSettingAppAction(
            priority=0,
            category=SettingsCategory.NETWORK,
            menu_item=IpMainMenu,
        ),
    )

    end_event = asyncio.Event()
    create_task(monitor_connections(end_event))
    create_task(monitor_interfaces(end_event))

    return [end_event.set]
