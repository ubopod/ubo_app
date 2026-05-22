# pyright: reportMissingModuleSource=false
# ruff: noqa: D100, D103
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
from typing import TYPE_CHECKING, Any, TypeVar

from bluetooth_interfaces import (
    ADAPTER_INTERFACE,
    BLUEZ_ADAPTER_PATH,
    BLUEZ_ROOT_PATH,
    BLUEZ_SERVICE,
    DEVICE_INTERFACE,
    BluezAdapterInterface,
    BluezDeviceInterface,
    DbusObjectManagerInterface,
)
from constants import BLUETOOTH_CONNECTED_ICON, BLUETOOTH_ICON, BLUETOOTH_OFF_ICON

from ubo_app.colors import DANGER_COLOR, INFO_COLOR, SUCCESS_COLOR
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.bluetooth import BluetoothDevice
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.bus_provider import get_system_bus
from ubo_app.utils.error_handlers import report_service_error

if TYPE_CHECKING:
    from asyncio.tasks import _FutureLike
    from collections.abc import Coroutine

T = TypeVar('T')

# Pairing can block for a while: it includes the agent passkey confirmation.
PAIR_TIMEOUT = 60.0

# Addresses with a pair_device call in flight, so repeated taps on the same
# device while pairing is running are ignored (module-level container, not a
# global).
_pairing_in_progress: set[str] = set()


def wait_for(task: _FutureLike[T], *, timeout: float = 10.0) -> Coroutine[Any, Any, T]:
    return asyncio.wait_for(task, timeout=timeout)


def _unwrap(value: object) -> object:
    """Unwrap an sdbus variant, represented as a ``(signature, value)`` tuple."""
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):  # noqa: PLR2004
        return value[1]
    return value


def get_object_manager() -> DbusObjectManagerInterface:
    return DbusObjectManagerInterface.new_proxy(
        bus=get_system_bus(),
        service_name=BLUEZ_SERVICE,
        object_path=BLUEZ_ROOT_PATH,
    )


async def _get_adapter_path() -> str:
    """Return the object path of the first Bluetooth adapter."""
    with contextlib.suppress(Exception):
        objects = await wait_for(get_object_manager().get_managed_objects())
        for path, interfaces in objects.items():
            if ADAPTER_INTERFACE in interfaces:
                return path
    return BLUEZ_ADAPTER_PATH


async def get_adapter() -> BluezAdapterInterface | None:
    if not IS_RPI:
        return None
    with contextlib.suppress(Exception):
        return BluezAdapterInterface.new_proxy(
            bus=get_system_bus(),
            service_name=BLUEZ_SERVICE,
            object_path=await _get_adapter_path(),
        )
    return None


def _device_proxy(adapter_path: str, address: str) -> BluezDeviceInterface:
    object_path = f'{adapter_path}/dev_{address.upper().replace(":", "_")}'
    return BluezDeviceInterface.new_proxy(
        bus=get_system_bus(),
        service_name=BLUEZ_SERVICE,
        object_path=object_path,
    )


async def power_on() -> None:
    """Power the adapter on so it can scan and accept connections."""
    if not IS_RPI:
        return
    adapter = await get_adapter()
    if adapter is None:
        logger.warning('No Bluetooth adapter found')
        return
    with contextlib.suppress(Exception):
        await adapter.powered.set_async(True)


async def get_adapter_state() -> tuple[bool, bool]:
    """Return ``(is_powered, is_scanning)`` for the adapter."""
    if not IS_RPI:
        return (False, False)
    adapter = await get_adapter()
    if adapter is None:
        return (False, False)
    try:
        return (await adapter.powered, await adapter.discovering)
    except Exception:
        logger.exception('Failed to read Bluetooth adapter state')
        return (False, False)


async def start_discovery() -> None:
    """Power on the adapter and start scanning for nearby devices."""
    if not IS_RPI:
        return
    adapter = await get_adapter()
    if adapter is None:
        logger.warning('No Bluetooth adapter found')
        return
    with contextlib.suppress(Exception):
        await adapter.powered.set_async(True)
    with contextlib.suppress(Exception):
        await wait_for(
            adapter.set_discovery_filter(
                {'Transport': ('s', 'auto'), 'DuplicateData': ('b', False)},
            ),
        )
    try:
        await wait_for(adapter.start_discovery())
    except Exception:
        logger.exception('Failed to start Bluetooth discovery')
        report_service_error()


async def stop_discovery() -> None:
    """Stop scanning for nearby devices."""
    if not IS_RPI:
        return
    adapter = await get_adapter()
    if adapter is None:
        return
    with contextlib.suppress(Exception):
        await wait_for(adapter.stop_discovery())


async def get_devices() -> list[BluetoothDevice]:
    """Return every known device (discovered or paired)."""
    if not IS_RPI:
        return []
    devices: list[BluetoothDevice] = []
    try:
        objects = await wait_for(get_object_manager().get_managed_objects())
    except Exception:
        logger.exception('Failed to enumerate Bluetooth devices')
        return []

    for interfaces in objects.values():
        if DEVICE_INTERFACE not in interfaces:
            continue
        props = interfaces[DEVICE_INTERFACE]
        address = _unwrap(props.get('Address'))
        if not address:
            continue
        rssi = _unwrap(props.get('RSSI'))
        devices.append(
            BluetoothDevice(
                address=str(address),
                name=str(
                    _unwrap(props.get('Alias'))
                    or _unwrap(props.get('Name'))
                    or address,
                ),
                icon=(
                    str(icon) if (icon := _unwrap(props.get('Icon'))) else None
                ),
                paired=bool(_unwrap(props.get('Paired'))),
                connected=bool(_unwrap(props.get('Connected'))),
                trusted=bool(_unwrap(props.get('Trusted'))),
                rssi=rssi if isinstance(rssi, int) else None,
            ),
        )
    return devices


def _notify(title: str, content: str, color: str, icon: str, chime: Chime) -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title=title,
                content=content,
                display_type=NotificationDisplayType.FLASH,
                color=color,
                icon=icon,
                chime=chime,
            ),
        ),
    )


async def _device_name(device: BluezDeviceInterface, address: str) -> str:
    with contextlib.suppress(Exception):
        return await device.alias or await device.name or address
    return address


async def pair_device(address: str) -> None:
    """Pair with, trust, and connect to the device at *address*.

    Pairing takes several seconds (it includes the passkey confirmation), so a
    sticky "pairing" notification is shown immediately and then replaced in
    place — same notification id — with the success or failure result. This
    gives the user continuous feedback and keeps repeated taps on the same
    device (while a pairing attempt is already running) from doing anything.
    """
    if not IS_RPI:
        return
    if address in _pairing_in_progress:
        # A pairing attempt for this device is already running; ignore re-taps.
        return
    _pairing_in_progress.add(address)
    try:
        adapter_path = await _get_adapter_path()
        device = _device_proxy(adapter_path, address)
        name = await _device_name(device, address)

        progress_notification = Notification(
            id=f'bluetooth:pairing:{address}',
            title=f'Pairing "{name}"',
            content=f'Pairing with "{name}", please wait…',
            display_type=NotificationDisplayType.STICKY,
            color=INFO_COLOR,
            icon=BLUETOOTH_ICON,
        )
        store.dispatch(NotificationsAddAction(notification=progress_notification))

        try:
            await wait_for(device.pair(), timeout=PAIR_TIMEOUT)
        except Exception:
            logger.exception(
                'Bluetooth pairing failed',
                extra={'address': address},
            )
            report_service_error()
            store.dispatch(
                NotificationsAddAction(
                    notification=replace(
                        progress_notification,
                        title=f'"{name}" pairing failed',
                        content=f'Could not pair with "{name}".',
                        display_type=NotificationDisplayType.FLASH,
                        color=DANGER_COLOR,
                        icon=BLUETOOTH_OFF_ICON,
                        chime=Chime.FAILURE,
                    ),
                ),
            )
            return

        with contextlib.suppress(Exception):
            await device.trusted.set_async(True)
        with contextlib.suppress(Exception):
            await wait_for(device.connect())

        logger.info('Bluetooth device paired', extra={'address': address})
        store.dispatch(
            NotificationsAddAction(
                notification=replace(
                    progress_notification,
                    title=f'"{name}" paired',
                    content=f'"{name}" was paired successfully.',
                    display_type=NotificationDisplayType.FLASH,
                    color=SUCCESS_COLOR,
                    icon=BLUETOOTH_CONNECTED_ICON,
                    chime=Chime.ADD,
                ),
            ),
        )
    finally:
        _pairing_in_progress.discard(address)


async def connect_device(address: str) -> None:
    """Connect to an already-paired device."""
    if not IS_RPI:
        return
    adapter_path = await _get_adapter_path()
    device = _device_proxy(adapter_path, address)
    try:
        await wait_for(device.connect())
    except Exception:
        logger.exception('Bluetooth connect failed', extra={'address': address})
        report_service_error()


async def disconnect_device(address: str) -> None:
    """Disconnect from a connected device."""
    if not IS_RPI:
        return
    adapter_path = await _get_adapter_path()
    device = _device_proxy(adapter_path, address)
    with contextlib.suppress(Exception):
        await wait_for(device.disconnect())


async def remove_device(address: str) -> None:
    """Unpair and forget the device at *address*."""
    if not IS_RPI:
        return
    adapter = await get_adapter()
    if adapter is None:
        return
    adapter_path = await _get_adapter_path()
    name = await _device_name(_device_proxy(adapter_path, address), address)
    object_path = f'{adapter_path}/dev_{address.upper().replace(":", "_")}'
    try:
        await wait_for(adapter.remove_device(object_path))
    except Exception:
        logger.exception('Bluetooth remove failed', extra={'address': address})
        report_service_error()
        return

    logger.info('Bluetooth device removed', extra={'address': address})
    _notify(
        f'"{name}" removed',
        f'"{name}" was removed successfully.',
        DANGER_COLOR,
        BLUETOOTH_OFF_ICON,
        Chime.DONE,
    )
