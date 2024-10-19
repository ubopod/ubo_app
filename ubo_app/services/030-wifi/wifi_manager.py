# pyright: reportMissingModuleSource=false
# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import TYPE_CHECKING, Any, TypeVar, cast

from debouncer import DebounceOptions, debounce
from ubo_gui.constants import DANGER_COLOR

from ubo_app.store.main import store
from ubo_app.store.services.ethernet import NetState
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.wifi import ConnectionState, WiFiConnection, WiFiType
from ubo_app.utils.bus_provider import get_system_bus

if TYPE_CHECKING:
    from asyncio.tasks import _FutureLike
    from collections.abc import Coroutine

from sdbus import dbus_exceptions
from sdbus.utils.inspect import (  # pyright: ignore [reportMissingImports]
    inspect_dbus_path,
)
from sdbus_async.networkmanager import (
    AccessPoint,
    ActiveConnection,
    DeviceState,
    NetworkConnectionSettings,
    NetworkDeviceGeneric,
    NetworkDeviceWireless,
    NetworkManager,
    NetworkManagerConnectionProperties,
    NetworkManagerSettings,
)
from sdbus_async.networkmanager.enums import (
    ConnectionState as SdBusConnectionState,
)
from sdbus_async.networkmanager.enums import DeviceType

RETRIES = 3

T = TypeVar('T')


def wait_for(task: _FutureLike[T]) -> Coroutine[Any, Any, T]:
    return asyncio.wait_for(task, timeout=10.0)


async def get_wifi_device() -> NetworkDeviceWireless | None:
    network_manager = NetworkManager(get_system_bus())
    devices_paths = await wait_for(network_manager.get_devices())
    for device_path in devices_paths:
        generic_device = NetworkDeviceGeneric(device_path, get_system_bus())
        if (
            await wait_for(
                generic_device.device_type,
            )
            == DeviceType.WIFI
        ):
            return NetworkDeviceWireless(device_path, get_system_bus())
    return None


async def get_wifi_device_state() -> NetState:
    wifi_device = await get_wifi_device()
    if wifi_device is None:
        return NetState.UNKNOWN

    state = await wifi_device.state
    if state is DeviceState.UNKNOWN:
        return NetState.UNKNOWN
    if state in (
        DeviceState.DISCONNECTED,
        DeviceState.UNMANAGED,
        DeviceState.UNAVAILABLE,
        DeviceState.FAILED,
    ):
        return NetState.DISCONNECTED
    if state in (DeviceState.NEED_AUTH,):
        return NetState.NEEDS_ATTENTION
    if state in (
        DeviceState.DEACTIVATING,
        DeviceState.PREPARE,
        DeviceState.CONFIG,
        DeviceState.IP_CONFIG,
        DeviceState.IP_CHECK,
        DeviceState.SECONDARIES,
    ):
        return NetState.PENDING
    if state == DeviceState.ACTIVATED:
        return NetState.CONNECTED

    return NetState.UNKNOWN


@debounce(wait=0.5, options=DebounceOptions(trailing=True, time_window=2))
async def request_scan() -> None:
    wifi_device = await get_wifi_device()
    if wifi_device:
        await wait_for(wifi_device.request_scan({}))


async def get_access_points() -> list[AccessPoint]:
    wifi_device = await get_wifi_device()
    if wifi_device is None:
        return []

    access_points = await wait_for(
        wifi_device.access_points,
    )
    return [
        AccessPoint(access_point_path, get_system_bus())
        for access_point_path in access_points
    ]


async def get_active_access_point() -> AccessPoint | None:
    wifi_device = await get_wifi_device()
    if wifi_device is None:
        return None

    active_access_point = await wait_for(
        wifi_device.active_access_point,
    )
    if not active_access_point or active_access_point == '/':
        return None

    return AccessPoint(active_access_point, get_system_bus())


async def get_active_access_point_ssid() -> str | None:
    active_access_point = await get_active_access_point()
    if not active_access_point:
        return None

    return (
        await wait_for(
            active_access_point.ssid,
        )
    ).decode('utf-8')


async def get_active_connection() -> ActiveConnection | None:
    wifi_device = await get_wifi_device()
    if wifi_device is None:
        return None

    active_connection = await wait_for(
        wifi_device.active_connection,
    )
    if not active_connection or active_connection == '/':
        return None

    return ActiveConnection(active_connection, get_system_bus())


async def get_active_connection_state() -> ConnectionState:
    active_connection = await get_active_connection()
    if not active_connection:
        return ConnectionState.UNKNOWN

    active_connection_state = (
        cast(SdBusConnectionState, await active_connection.state)
        if active_connection
        else None
    )

    return {
        SdBusConnectionState.ACTIVATED: ConnectionState.CONNECTED,
        SdBusConnectionState.ACTIVATING: ConnectionState.CONNECTING,
        SdBusConnectionState.DEACTIVATED: ConnectionState.DISCONNECTED,
        SdBusConnectionState.DEACTIVATING: ConnectionState.DISCONNECTED,
        SdBusConnectionState.UNKNOWN: ConnectionState.UNKNOWN,
        None: ConnectionState.UNKNOWN,
    }[active_connection_state]


async def get_active_connection_ssid() -> str | None:
    active_connection = await get_active_connection()
    if not active_connection:
        return None

    try:
        connection = NetworkConnectionSettings(await active_connection.connection)

        settings = await connection.get_settings()
        return settings['802-11-wireless']['ssid'][1].decode('utf-8')
    except dbus_exceptions.DbusUnknownMethodError:
        return None


async def get_saved_ssids() -> list[str]:
    network_manager_settings = NetworkManagerSettings(get_system_bus())
    connections = [
        NetworkConnectionSettings(i, get_system_bus())
        for i in await wait_for(
            network_manager_settings.connections,
        )
    ]
    connections_settings = [
        await wait_for(
            i.get_settings(),
        )
        for i in connections
    ]
    return [
        settings['802-11-wireless']['ssid'][1].decode('utf-8')
        for settings in connections_settings
        if '802-11-wireless' in settings
    ]


async def add_wireless_connection(
    ssid: str,
    password: str,
    type: WiFiType,
    *,
    hidden: bool | None = False,
) -> None:
    wifi_device = await get_wifi_device()
    if not wifi_device:
        return

    access_points = [
        (
            access_point,
            await wait_for(
                access_point.ssid,
            ),
        )
        for access_point in await get_access_points()
    ]
    access_point = next(
        (
            access_point
            for access_point, ssid_ in access_points
            if ssid_.decode('utf8') == ssid
        ),
        None,
    )

    if type == WiFiType.NOPASS:
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
    from ubo_app.logging import logger

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

    network_manager = NetworkManager(get_system_bus())
    connection = await wait_for(
        network_manager.add_and_activate_connection(
            properties,
            inspect_dbus_path(wifi_device),
            inspect_dbus_path(access_point) if access_point else '/',
        ),
    )

    logger.info('Connection added', extra={'connection': connection})


async def connect_wireless_connection(ssid: str) -> None:
    wifi_device = await get_wifi_device()

    if not wifi_device:
        return

    network_manager_settings = NetworkManagerSettings(get_system_bus())
    connections = [
        NetworkConnectionSettings(path, get_system_bus())
        for path in await wait_for(
            network_manager_settings.connections,
        )
    ]
    connections_settings = [
        (
            await wait_for(
                connection.get_settings(),
            ),
            inspect_dbus_path(connection),
        )
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

    network_manager = NetworkManager(get_system_bus())
    await wait_for(
        network_manager.activate_connection(
            desired_connection,
            inspect_dbus_path(wifi_device),
        ),
    )


async def disconnect_wireless_connection() -> None:
    wifi_device = await get_wifi_device()
    if not wifi_device:
        return

    network_manager = NetworkManager(get_system_bus())
    await wait_for(
        network_manager.deactivate_connection(
            await wait_for(
                wifi_device.active_connection,
            ),
        ),
    )


async def forget_wireless_connection(ssid: str) -> None:
    network_manager_settings = NetworkManagerSettings(get_system_bus())

    for connection_path in await wait_for(
        network_manager_settings.connections,
    ):
        network_connection_settings = NetworkConnectionSettings(
            connection_path,
            get_system_bus(),
        )
        settings = await wait_for(
            network_connection_settings.get_settings(),
        )
        if (
            '802-11-wireless' in settings
            and settings['802-11-wireless']['ssid'][1].decode('utf-8') == ssid
        ):
            await wait_for(network_connection_settings.delete())
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title=f'"{ssid}" Deleted',
                        content=f"""WiFi connection with ssid "{
                        ssid}" was deleted successfully""",
                        display_type=NotificationDisplayType.FLASH,
                        color=DANGER_COLOR,
                        icon='󱛅',
                        chime=Chime.DONE,
                    ),
                ),
            )


async def get_connections() -> list[WiFiConnection]:
    # It is need as this action is not atomic and the active_connection may not be
    # available when active_connection.state is queried
    for _ in range(RETRIES):
        with contextlib.suppress(Exception):
            active_connection_state = await get_active_connection_state()
            active_connection_ssid = await get_active_connection_ssid()
            saved_ssids = await get_saved_ssids()
            access_point_by_ssids = {
                (
                    await wait_for(
                        i.ssid,
                    )
                ).decode('utf-8'): i
                for i in await get_access_points()
            }

            return [
                WiFiConnection(
                    ssid=ssid,
                    signal_strength=await wait_for(
                        access_point_by_ssids[ssid].strength,
                    )
                    if ssid in access_point_by_ssids
                    else 0,
                    state=active_connection_state
                    if active_connection_ssid == ssid
                    else ConnectionState.DISCONNECTED,
                )
                for ssid in saved_ssids
            ]
        await asyncio.sleep(0.5)
    return []
