# ruff: noqa: D100, D103
from __future__ import annotations

import asyncio
import socket
from collections import defaultdict
from contextlib import suppress
from typing import TYPE_CHECKING

import psutil

from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.ip import (
    IpNetworkInterface,
    IpSetIsConnectedAction,
    IpUpdateInterfacesAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_app.utils.types import Subscriptions

from constants import IP_ADDRESSES_MENU_ID

PING_TIMEOUT = 3.0


def _get_interface_icon(name: str) -> str:
    """Get the icon for a network interface based on its name."""
    if name.startswith('eth'):
        return '󰈀'
    if name.startswith('wlan'):
        return ''
    if name.startswith('lo'):
        return '󰕇'
    return '󰛳'


def _register_ip_action_handlers(interfaces: Sequence[IpNetworkInterface]) -> None:
    """Register action handlers for IP interface menus."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
        unregister_action,
    )

    # Unregister all existing ip:open-interface: handlers
    for action_id in get_registered_actions():
        if action_id.startswith('ip:open-interface:'):
            unregister_action(action_id)

    if not interfaces:
        return

    # Register handlers for each interface
    for interface in interfaces:
        name = interface.name

        def _make_handler(interface_name: str) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(StackPushMenuAction(menu_key=interface_name))

            return _handler

        register_action(f'ip:open-interface:{name}', _make_handler(name))


@store.autorun(lambda state: state.ip.interfaces)
def update_ip_dynamic_menu(interfaces: Sequence[IpNetworkInterface]) -> None:
    """Update the dynamic menu for IP addresses (dumb UI architecture).

    This autorun dispatches UpdateDynamicMenuAction with serializable MenuItemData.
    The dynamic menus state is then used by ViewRenderer for rendering.
    """
    # Register action handlers for interface navigation
    _register_ip_action_handlers(interfaces)

    items: tuple[MenuItemData | None, ...] = ()
    if interfaces:
        items = tuple(
            MenuItemData(
                key=f'interface:{interface.name}',
                label=interface.name,
                icon=_get_interface_icon(interface.name),
                action_id=f'ip:open-interface:{interface.name}',
            )
            for interface in interfaces
        )

    logger.debug(
        '[IP Service] Updating dynamic menu: %d interfaces',
        len(interfaces) if interfaces else 0,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=IP_ADDRESSES_MENU_ID,
            title='󰩟IP Addresses',
            items=items,
            placeholder='No IP addresses',
        ),
    )

    # Create dynamic menus for each interface's detail page
    for interface in interfaces:
        interface_items = tuple(
            MenuItemData(
                key=f'ip:{interface.name}:{ip_address}',
                label=ip_address,
                icon='󰩠',
            )
            for ip_address in interface.ip_addresses
        )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=interface.name,
                title=f'󰩟{interface.name}',
                items=interface_items,
                placeholder='No IP addresses',
            ),
        )


_last_interfaces: list[IpNetworkInterface] | None = None


def load_network_interfaces() -> None:
    global _last_interfaces  # noqa: PLW0603

    ip_addresses_by_interface = defaultdict(list)
    for interface_name, ip_addresses in psutil.net_if_addrs().items():
        for address in ip_addresses:
            if address.family == socket.AddressFamily.AF_INET:
                ip_addresses_by_interface[interface_name].append(address.address)

    new_interfaces = [
        IpNetworkInterface(name=interface_name, ip_addresses=ip_addresses)
        for interface_name, ip_addresses in ip_addresses_by_interface.items()
    ]

    # Skip dispatch if interfaces haven't changed
    if _last_interfaces is not None and _last_interfaces == new_interfaces:
        return

    _last_interfaces = new_interfaces
    store.dispatch(IpUpdateInterfacesAction(interfaces=new_interfaces))


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


async def init_service() -> Subscriptions:
    store.dispatch(
        RegisterSettingAppAction(
            priority=0,
            category=SettingsCategory.NETWORK,
            label='IP Addresses',
            icon='󰩟',
        ),
    )

    # Register path matcher for IP addresses menu navigation
    from ubo_app.store.core.view_registry import register_path_menu_matcher

    def _ip_path_matcher(path: tuple[str, ...]) -> str | None:
        if len(path) >= 4 and path[3] == 'ip:':  # noqa: PLR2004
            if len(path) == 4:  # noqa: PLR2004
                return IP_ADDRESSES_MENU_ID
            # Interface detail page: path[4] is the interface name (e.g. 'en0')
            if len(path) == 5:  # noqa: PLR2004
                return path[4]
        return None

    register_path_menu_matcher('ip:settings', _ip_path_matcher)

    end_event = asyncio.Event()
    create_task(monitor_connections(end_event))
    create_task(monitor_interfaces(end_event))

    return [end_event.set]
