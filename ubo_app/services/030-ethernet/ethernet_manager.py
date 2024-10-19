# pyright: reportMissingModuleSource=false
# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypeVar

from ubo_app.store.services.ethernet import NetState
from ubo_app.utils.bus_provider import get_system_bus

if TYPE_CHECKING:
    from asyncio.tasks import _FutureLike
    from collections.abc import Coroutine


T = TypeVar('T')


def wait_for(task: _FutureLike[T]) -> Coroutine[Any, Any, T]:
    return asyncio.wait_for(task, timeout=10.0)


from sdbus_async.networkmanager import (  # noqa: E402
    DeviceState,
    NetworkDeviceGeneric,
    NetworkManager,
)
from sdbus_async.networkmanager.enums import DeviceType  # noqa: E402

system_buses = {}


async def get_ethernet_device() -> NetworkDeviceGeneric | None:
    network_manager = NetworkManager(get_system_bus())
    devices_paths = await wait_for(network_manager.get_devices())
    for device_path in devices_paths:
        generic_device = NetworkDeviceGeneric(device_path, get_system_bus())
        if await wait_for(generic_device.device_type) == DeviceType.ETHERNET:
            return generic_device
    return None


async def get_ethernet_device_state() -> NetState:
    ethernet_device = await get_ethernet_device()
    if ethernet_device is None:
        return NetState.UNKNOWN

    state = await ethernet_device.state
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
