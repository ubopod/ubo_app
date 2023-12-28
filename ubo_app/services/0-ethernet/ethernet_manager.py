# pyright: reportMissingImports=false
# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import asyncio
from pathlib import Path
from threading import current_thread
from typing import TYPE_CHECKING, Any, Coroutine, TypeVar

from ubo_app.store.ethernet import GlobalEthernetState
from ubo_app.utils.fake import Fake

if TYPE_CHECKING:
    from asyncio.tasks import _FutureLike


T = TypeVar('T')


def wait_for(task: _FutureLike[T]) -> Coroutine[Any, Any, T]:
    return asyncio.wait_for(task, timeout=10.0)


IS_RPI = Path('/etc/rpi-issue').exists()
if not IS_RPI:
    import sys

    sys.modules['sdbus'] = Fake()
    sys.modules['sdbus_async'] = Fake()
    sys.modules['sdbus_async.networkmanager'] = Fake()
    sys.modules['sdbus_async.networkmanager.enums'] = Fake()


from sdbus import SdBus, sd_bus_open_system, set_default_bus  # noqa: E402
from sdbus_async.networkmanager import (  # noqa: E402
    DeviceState,
    NetworkDeviceGeneric,
    NetworkManager,
)
from sdbus_async.networkmanager.enums import (  # noqa: E402
    DeviceType,
)

system_buses = {}


def get_system_bus() -> SdBus:
    thread = current_thread()
    if thread not in system_buses:
        system_buses[thread] = sd_bus_open_system()
    set_default_bus(system_buses[thread])
    return system_buses[thread]


async def get_ethernet_device() -> NetworkDeviceGeneric | None:
    network_manager = NetworkManager(get_system_bus())
    devices_paths = await wait_for(
        network_manager.get_devices(),
    )
    for device_path in devices_paths:
        generic_device = NetworkDeviceGeneric(device_path, get_system_bus())
        if (
            await wait_for(
                generic_device.device_type,
            )
            == DeviceType.ETHERNET
        ):
            return generic_device
    return None


async def get_ethernet_device_state() -> GlobalEthernetState:
    ethernet_device = await get_ethernet_device()
    if ethernet_device is None:
        return GlobalEthernetState.UNKNOWN

    state = await ethernet_device.state
    if state is DeviceState.UNKNOWN:
        return GlobalEthernetState.UNKNOWN
    if state in (
        DeviceState.DISCONNECTED,
        DeviceState.UNMANAGED,
        DeviceState.UNAVAILABLE,
        DeviceState.FAILED,
    ):
        return GlobalEthernetState.DISCONNECTED
    if state in (DeviceState.NEED_AUTH,):
        return GlobalEthernetState.NEEDS_ATTENTION
    if state in (
        DeviceState.DEACTIVATING,
        DeviceState.PREPARE,
        DeviceState.CONFIG,
        DeviceState.IP_CONFIG,
        DeviceState.IP_CHECK,
        DeviceState.SECONDARIES,
    ):
        return GlobalEthernetState.PENDING
    if state == DeviceState.ACTIVATED:
        return GlobalEthernetState.CONNECTED

    return GlobalEthernetState.UNKNOWN
