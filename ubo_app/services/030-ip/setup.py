# ruff: noqa: D100, D103
from __future__ import annotations

import asyncio
import socket
from collections import defaultdict
from contextlib import suppress
from typing import TYPE_CHECKING

import psutil
from ubo_gui.menu.types import HeadlessMenu, Item, SubMenuItem

from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.ip import (
    IpNetworkInterface,
    IpSetIsConnectedAction,
    IpUpdateInterfacesAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.utils.types import Subscriptions

PING_TIMEOUT = 3.0


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
            report_service_error()
        finally:
            await asyncio.sleep(1)


async def monitor_connections(end_event: asyncio.Event) -> None:
    received_lines: list[tuple[bytes, float]] = []
    loop = asyncio.get_event_loop()

    async def ping_process() -> None:
        while not end_event.is_set():
            process = None
            try:
                logger.debug(
                    'Starting ping subprocess to monitor internet connectivity',
                )
                process = await asyncio.create_subprocess_exec(
                    '/usr/bin/env',
                    'ping',
                    '8.8.8.8',
                    '-s',
                    '0',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                if process.stdout:
                    async for line in process.stdout:
                        if end_event.is_set():
                            logger.debug('End event set, terminating ping process')
                            process.terminate()
                            return
                        received_lines.append((line, loop.time()))
                # If we reach here, ping process exited - wait before retry
                logger.warning(
                    'Ping process exited, restarting in 1 second...',
                    extra={'return_code': process.returncode if process else None},
                )
                await asyncio.sleep(1)
            except Exception:
                logger.exception('Error in ping process, restarting in 1 second...')
                if process:
                    with suppress(Exception):
                        process.terminate()
                await asyncio.sleep(1)

    create_task(ping_process())

    previous_state = None
    while not end_event.is_set():
        received_lines = [
            line
            for line in received_lines
            if loop.time() - line[1] < PING_TIMEOUT
            and line[0].startswith(b'8 bytes from')
        ]
        is_connected = bool(
            received_lines and received_lines[-1][0].startswith(b'8 bytes from'),
        )
        if is_connected != previous_state:
            logger.info(
                'Internet connectivity state changed',
                extra={
                    'is_connected': is_connected,
                    'received_lines_count': len(received_lines),
                },
            )
            previous_state = is_connected
        store.dispatch(IpSetIsConnectedAction(is_connected=is_connected))
        await asyncio.sleep(0.25)


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
