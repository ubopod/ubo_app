# pyright: reportMissingImports=false
# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

from typing import Callable

from ubo_app.utils import IS_RPI
from ubo_app.utils.bus_provider import get_system_bus

if not IS_RPI:
    import sys

    from ubo_app.utils.fake import Fake

    sys.modules['sdbus'] = Fake()

from sdbus import DbusInterfaceCommonAsync, dbus_property_async


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
            result.append('_%02x' % ord(char))
    return ''.join(result)


async def monitor_unit(unit_name: str, callback: Callable[[str], None]) -> None:
    bus = get_system_bus()
    system_service = SystemdUnitInterface.new_proxy(
        bus=bus,
        service_name='org.freedesktop.systemd1',
        object_path=f'/org/freedesktop/systemd1/unit/{to_dbus_string(unit_name)}',
    )

    async for _ in system_service.properties_changed:
        active_state = await system_service.active_state
        callback(active_state)
