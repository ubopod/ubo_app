# pyright: reportMissingImports=false
# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING

from sdbus import DbusInterfaceCommonAsync, dbus_property_async

from ubo_app.utils.bus_provider import get_system_bus

if TYPE_CHECKING:
    from collections.abc import Callable


class SystemdUnitInterface(  # pyright: ignore [reportGeneralTypeIssues]
    DbusInterfaceCommonAsync,
    interface_name='org.freedesktop.systemd1.Unit',  # pyright: ignore [reportCallIssue]
):
    @dbus_property_async(property_signature='s')
    def active_state(self: SystemdUnitInterface) -> str:
        raise NotImplementedError


def to_dbus_string(string: str) -> str:
    """Convert a string to a D-Bus object path."""
    result = []
    for char in string:
        if char.isalnum() or char == '_':
            result.append(char)
        else:
            result.append(f'_{ord(char):02x}')
    return ''.join(result)


async def monitor_unit(unit_name: str, callback: Callable[[str], None]) -> None:
    """Monitor the active state of a systemd unit."""
    bus = get_system_bus()
    system_service = SystemdUnitInterface.new_proxy(
        bus=bus,
        service_name='org.freedesktop.systemd1',
        object_path=f'/org/freedesktop/systemd1/unit/{to_dbus_string(unit_name)}',
    )

    async for _ in system_service.properties_changed:
        active_state = await system_service.active_state
        callback(active_state)


async def is_unit_active(unit: str) -> bool:
    """Check if the systemd unit is active."""
    process = await asyncio.create_subprocess_exec(
        '/usr/bin/env',
        'systemctl',
        'is-active',
        unit,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    return stdout.strip() == b'active'


async def is_unit_enabled(unit: str) -> bool:
    """Check if the systemd unit is enabled."""
    process = await asyncio.create_subprocess_exec(
        '/usr/bin/env',
        'systemctl',
        'is-enabled',
        unit,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    return stdout.strip() == b'enabled'
