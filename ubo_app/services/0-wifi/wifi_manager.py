# pyright: reportMissingImports=false
# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import uuid
from pathlib import Path
from threading import current_thread
from types import ModuleType
from typing import Any, Awaitable, Callable, Generator, Iterator

from ubo_app.logging import logger
from ubo_app.store.wifi import WiFiConnection, WiFiType
from ubo_app.utils.async_ import create_task

IS_RPI = Path('/etc/rpi-issue').exists()
if not IS_RPI:
    import sys

    class Fake(ModuleType):
        def __init__(self: Fake) -> None:
            super().__init__('')

        def __getattr__(self: Fake, attr: str) -> Fake | str:
            logger.verbose(
                'Accessing fake attribute of a `Fake` instance',
                extra={'attr': attr},
            )
            if attr in ['__file__']:
                return ''
            return Fake()

        def __call__(self: Fake, *args: object, **kwargs: dict[str, Any]) -> Fake:
            logger.verbose(
                'Calling a `Fake` instance',
                extra={'args_': args, 'kwargs': kwargs},
            )
            return Fake()

        def __await__(self: Fake) -> Generator[Fake | None, Any, Any]:
            yield None
            return Fake()

        def __iter__(self: Fake) -> Iterator[Fake]:
            return iter([Fake()])

    sys.modules['sdbus'] = Fake()
    sys.modules['sdbus_async'] = Fake()
    sys.modules['sdbus_async.networkmanager'] = Fake()
    sys.modules['sdbus_async.networkmanager.enums'] = Fake()


from sdbus import SdBus, sd_bus_open_system, set_default_bus  # noqa: E402
from sdbus_async.networkmanager import (  # noqa: E402
    AccessPoint,
    NetworkConnectionSettings,
    NetworkDeviceGeneric,
    NetworkDeviceWireless,
    NetworkManager,
    NetworkManagerConnectionProperties,
    NetworkManagerSettings,
)
from sdbus_async.networkmanager.enums import DeviceType  # noqa: E402

system_buses = {}


async def get_wifi_device(
    system_bus: SdBus | None = None,
) -> NetworkDeviceWireless | None:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    try:
        network_manager = NetworkManager(system_bus_)
        logger.verbose(22221, extra={'thread': current_thread(), 'bus': system_bus_})
        devices_paths = await network_manager.get_devices()
        logger.verbose(22222)
        for device_path in devices_paths:
            generic_device = NetworkDeviceGeneric(device_path, system_bus_)
            if await generic_device.device_type == DeviceType.WIFI:
                return NetworkDeviceWireless(device_path, system_bus_)
        return None
    finally:
        if not system_bus:
            system_bus_.close()


async def subscribe_to_wifi_device(
    event_handler: Callable[[object], Any],
) -> None:
    while True:
        system_bus = sd_bus_open_system()
        set_default_bus(system_bus)

        try:
            wifi_device = await get_wifi_device(system_bus)
            if not wifi_device:
                continue

            async for event in wifi_device.properties_changed:
                result = event_handler(event)
                if isinstance(result, Awaitable):
                    create_task(result)
        finally:
            system_bus.close()


async def request_scan(system_bus: SdBus | None = None) -> None:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    try:
        wifi_device = await get_wifi_device(system_bus_)
        if wifi_device:
            await wifi_device.request_scan({})
    finally:
        if not system_bus:
            system_bus_.close()


async def get_access_points(
    system_bus: SdBus | None = None,
) -> list[AccessPoint]:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    try:
        wifi_device = await get_wifi_device(system_bus_)
        if wifi_device is None:
            return []

        access_points = await wifi_device.access_points
        return [
            AccessPoint(access_point_path, system_bus_)
            for access_point_path in access_points
        ]
    finally:
        if not system_bus:
            system_bus_.close()


async def get_active_access_point(
    system_bus: SdBus | None = None,
) -> AccessPoint | None:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    try:
        wifi_device = await get_wifi_device(system_bus_)
        if wifi_device is None:
            return None

        active_access_point = await wifi_device.active_access_point
        if not active_access_point or active_access_point == '/':
            return None

        return AccessPoint(active_access_point, system_bus_)
    finally:
        if not system_bus:
            system_bus_.close()


async def get_saved_ssids(
    system_bus: SdBus | None = None,
) -> list[str]:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    try:
        network_manager_settings = NetworkManagerSettings(system_bus_)
        connections = [
            NetworkConnectionSettings(i, system_bus_)
            for i in await network_manager_settings.connections
        ]
        connections_settings = [await i.get_settings() for i in connections]
        return [
            settings['802-11-wireless']['ssid'][1].decode('utf-8')
            for settings in connections_settings
            if '802-11-wireless' in settings
        ]
    finally:
        if not system_bus:
            system_bus_.close()


async def get_active_ssid(system_bus: SdBus | None = None) -> str | None:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    try:
        active_access_point = await get_active_access_point(system_bus_)
        if not active_access_point:
            return None

        return (await active_access_point.ssid).decode('utf-8')
    finally:
        if not system_bus:
            system_bus_.close()


async def add_wireless_connection(
    ssid: str,
    password: str,
    type: WiFiType,
    *,
    hidden: bool | None = False,
    system_bus: SdBus | None = None,
) -> None:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    try:
        wifi_device = await get_wifi_device(system_bus_)
        if not wifi_device:
            return

        access_points = [
            (access_point, await access_point.ssid)
            for access_point in await get_access_points(system_bus_)
        ]
        access_point = next(
            (
                access_point
                for access_point, ssid_ in access_points
                if ssid_.decode('utf8') == ssid
            ),
            None,
        )

        if not access_point:
            return

        if type == WiFiType.nopass:
            security = {
                'key-mgmt': ('s', 'none'),
                'auth-alg': ('s', 'open'),
            }
        elif type == WiFiType.WEP:
            security = {
                'key-mgmt': ('s', 'none'),
                'auth-alg': ('s', 'open'),
                'psk': ('s', password),
            }
        elif type in (WiFiType.WPA, WiFiType.WPA2):
            security = {
                'key-mgmt': ('s', 'wpa-psk'),
                'auth-alg': ('s', 'open'),
                'psk': ('s', password),
            }

        properties: NetworkManagerConnectionProperties = {
            'connection': {
                'id': ('s', ssid),
                'uuid': ('s', str(uuid.uuid4())),
                'type': ('s', '802-11-wireless'),
                'autoconnect': ('b', True),
            },
            '802-11-wireless': {
                'mode': ('s', 'infrastructure'),
                'security': ('s', '802-11-wireless-security'),
                'ssid': ('ay', ssid.encode('utf-8')),
                'hidden': ('b', hidden),
            },
            '802-11-wireless-security': security,
            'ipv4': {'method': ('s', 'auto')},
            'ipv6': {'method': ('s', 'auto')},
        }

        network_manager = NetworkManager(system_bus_)
        await network_manager.add_and_activate_connection(
            properties,
            wifi_device._remote_object_path,  # noqa: SLF001
            access_point._remote_object_path,  # noqa: SLF001
        )
    finally:
        if not system_bus:
            system_bus_.close()


async def connect_wireless_connection(
    ssid: str,
    *,
    system_bus: SdBus | None = None,
) -> None:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    try:
        wifi_device = await get_wifi_device(system_bus_)

        if not wifi_device:
            return

        network_manager_settings = NetworkManagerSettings(system_bus_)
        connections = [
            NetworkConnectionSettings(path, system_bus_)
            for path in await network_manager_settings.connections
        ]
        connections_settings = [
            (await connection.get_settings(), connection._remote_object_path)  # noqa: SLF001
            for connection in connections
        ]
        desired_connection = next(
            (
                path
                for settings, path in connections_settings
                if '802-11-wireless' in settings
                and settings['802-11-wireless']['ssid'][1].decode('utf-8') == ssid
            ),
            None,
        )

        if not desired_connection:
            return

        network_manager = NetworkManager(system_bus_)
        await network_manager.activate_connection(
            desired_connection,
            wifi_device._remote_object_path,  # noqa: SLF001
        )
    finally:
        if not system_bus:
            system_bus_.close()


async def disconnect_wireless_connection(*, system_bus: SdBus | None = None) -> None:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    try:
        wifi_device = await get_wifi_device(system_bus_)
        if not wifi_device:
            return

        network_manager = NetworkManager(system_bus_)
        await network_manager.deactivate_connection(await wifi_device.active_connection)
    finally:
        if not system_bus:
            system_bus_.close()


async def forget_wireless_connection(
    ssid: str,
    *,
    system_bus: SdBus | None = None,
) -> None:
    if system_bus:
        system_bus_ = system_bus
    else:
        system_bus_ = sd_bus_open_system()
        set_default_bus(system_bus_)

    network_manager_settings = NetworkManagerSettings(system_bus_)

    try:
        for connection_path in await network_manager_settings.connections:
            network_connection_settings = NetworkConnectionSettings(
                connection_path,
                system_bus_,
            )
            settings = await network_connection_settings.get_settings()
            if (
                '802-11-wireless' in settings
                and settings['802-11-wireless']['ssid'][1].decode('utf-8') == ssid
            ):
                await network_connection_settings.delete()
    finally:
        if not system_bus:
            system_bus_.close()


async def get_connections() -> list[WiFiConnection]:
    system_bus = sd_bus_open_system()
    set_default_bus(system_bus)

    active_ssid = await get_active_ssid(system_bus)
    saved_ssids = await get_saved_ssids(system_bus)
    access_point_ssids = {
        (await i.ssid).decode('utf-8'): i for i in await get_access_points(system_bus)
    }

    return [
        WiFiConnection(
            ssid=ssid,
            signal_strength=await access_point_ssids[ssid].strength
            if ssid in access_point_ssids
            else 0,
            is_active=active_ssid == ssid,
        )
        for ssid in saved_ssids
    ]
