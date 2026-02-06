# ruff: noqa: D100, D103
"""Setup and initialization for the Zigbee service."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from constants import ZIGBEE_MENU_PRIORITY
from pages import main as main_page
from zha.application.const import RadioType
from zigbee import (
    DEFAULT_PAIRING_DURATION,
    DeviceController,
    DevicePairingManager,
    NetworkManager,
    discover_coordinators,
)

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    # Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.zigbee import (
    ZigbeeBackup,
    ZigbeeConnectEvent,
    ZigbeeConnectionState,
    ZigbeeCoordinator,
    ZigbeeCreateBackupEvent,
    ZigbeeDeleteBackupEvent,
    ZigbeeDetectCoordinatorsEvent,
    ZigbeeDevice,
    ZigbeeDeviceInitializedEvent,
    ZigbeeDeviceJoinedEvent,
    ZigbeeDisconnectEvent,
    ZigbeePairingStartedEvent,
    ZigbeePairingStoppedEvent,
    ZigbeeRefreshDevicesEvent,
    ZigbeeResetNetworkEvent,
    ZigbeeRestoreBackupEvent,
    ZigbeeSetConnectionStateAction,
    ZigbeeSetDetectingAction,
    ZigbeeSetPairingStateAction,
    ZigbeeToggleEntityEvent,
    ZigbeeUpdateBackupsAction,
    ZigbeeUpdateCoordinatorsAction,
    ZigbeeUpdateDevicesAction,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions

# Global network manager instance
_network_manager: NetworkManager | None = None
_pairing_manager: DevicePairingManager | None = None
_pairing_task: asyncio.Task | None = None
_unsubscribe_pairing: callable | None = None


def get_network_manager() -> NetworkManager:
    """Get the global network manager instance."""
    global _network_manager
    if _network_manager is None:
        _network_manager = NetworkManager()
    return _network_manager


async def _detect_coordinators(_: ZigbeeDetectCoordinatorsEvent) -> None:
    """Handle coordinator detection request."""
    logger.info('Detecting Zigbee coordinators...')
    try:
        detected = await discover_coordinators()
        manager = get_network_manager()

        coordinators = [
            ZigbeeCoordinator(
                port=coord.port,
                description=coord.description,
                radio_type=coord.radio_type.name,
                baudrate=coord.baudrate,
                name=manager.get_coordinator_name(coord.port),
                has_network=manager.has_existing_network(coord),
            )
            for coord in detected
        ]

        logger.info(
            'Found %d coordinator(s)',
            len(coordinators),
            extra={
                'coordinator_ports': [c.port for c in coordinators],
                'coordinator_details': [
                    {'port': c.port, 'description': c.description, 'radio_type': c.radio_type}
                    for c in coordinators
                ],
            },
        )
        store.dispatch(ZigbeeUpdateCoordinatorsAction(coordinators=coordinators))
    except Exception:
        logger.exception('Failed to detect coordinators')
        store.dispatch(
            ZigbeeSetDetectingAction(is_detecting=False),
            NotificationsAddAction(
                notification=Notification(
                    title='Detection Failed',
                    content='Could not detect Zigbee coordinators',
                    display_type=NotificationDisplayType.FLASH,
                    color=DANGER_COLOR,
                    icon='󰈅',
                )
            ),
        )


async def _connect_coordinator(event: ZigbeeConnectEvent) -> None:
    """Handle coordinator connection request."""
    from zigbee.coordinator_probe import DetectedCoordinator as DetectedCoord

    logger.info('Connecting to coordinator: %s', event.coordinator.port)
    manager = get_network_manager()

    try:
        # Convert back to DetectedCoordinator
        detected = DetectedCoord(
            port=event.coordinator.port,
            description=event.coordinator.description,
            radio_type=RadioType[event.coordinator.radio_type],
            baudrate=event.coordinator.baudrate,
        )

        await manager.start_network(detected)

        store.dispatch(
            ZigbeeSetConnectionStateAction(
                state=ZigbeeConnectionState.CONNECTED,
                coordinator=event.coordinator,
            ),
        )
    except Exception:
        logger.exception('Failed to connect to coordinator')
        store.dispatch(
            ZigbeeSetConnectionStateAction(state=ZigbeeConnectionState.ERROR),
            NotificationsAddAction(
                notification=Notification(
                    title='Connection Failed',
                    content='Could not connect to Zigbee coordinator',
                    display_type=NotificationDisplayType.FLASH,
                    color=DANGER_COLOR,
                    icon='󰈅',
                )
            ),
        )


async def _disconnect_coordinator(_: ZigbeeDisconnectEvent) -> None:
    """Handle coordinator disconnection request."""
    logger.info('Disconnecting from coordinator')
    manager = get_network_manager()
    global _pairing_manager, _unsubscribe_pairing

    # Clean up pairing
    if _unsubscribe_pairing:
        _unsubscribe_pairing()
        _unsubscribe_pairing = None
    _pairing_manager = None

    try:
        await manager.shutdown()
        logger.info('Disconnected successfully')
    except Exception:
        logger.exception('Error during disconnect')


async def _refresh_devices(_: ZigbeeRefreshDevicesEvent) -> None:
    """Refresh the device list from the gateway."""
    manager = get_network_manager()
    if not manager.is_running:
        return

    try:
        raw_devices = manager.get_devices()
        devices = [
            ZigbeeDevice(
                ieee=str(dev['ieee']),
                nwk=dev['nwk'],
                manufacturer=dev['manufacturer'],
                model=dev['model'],
                name=dev['name'],
                custom_name=dev['custom_name'],
                available=dev['available'],
            )
            for dev in raw_devices
        ]
        store.dispatch(ZigbeeUpdateDevicesAction(devices=devices))

        # Also refresh backups
        raw_backups = manager.get_backups()
        backups = [
            ZigbeeBackup(
                index=b['index'],
                backup_time=b['backup_time'],
                device_count=b['device_count'],
                is_complete=b['is_complete'],
            )
            for b in raw_backups
        ]
        store.dispatch(ZigbeeUpdateBackupsAction(backups=backups))
    except Exception:
        logger.exception('Failed to refresh devices')


async def _start_pairing(event: ZigbeePairingStartedEvent) -> None:
    """Enable pairing mode on the coordinator."""
    global _pairing_manager, _unsubscribe_pairing, _pairing_task

    manager = get_network_manager()
    if not manager.is_running or manager.gateway is None:
        logger.warning('Cannot start pairing: network not running')
        store.dispatch(ZigbeeSetPairingStateAction(is_pairing=False))
        return

    try:
        _pairing_manager = DevicePairingManager(manager.gateway)

        def on_device_joined(event: object) -> None:
            logger.info('Device joined: %s', event)
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Device Joining',
                        content='A new device is connecting...',
                        display_type=NotificationDisplayType.FLASH,
                        color=WARNING_COLOR,
                        icon='󰐕',
                    )
                )
            )
            # Emit event for UI updates - event is DeviceJoinedEvent with ieee/nwk attrs
            ieee = getattr(event, 'ieee', None)
            nwk = getattr(event, 'nwk', None)
            if ieee is not None and nwk is not None:
                store.dispatch(
                    ZigbeeDeviceJoinedEvent(
                        ieee=str(ieee),
                        nwk=nwk,
                    )
                )

        def on_device_initialized(event: object) -> None:
            logger.info('Device initialized: %s', event)
            # Event is a DeviceFullInitEvent object with device_info attribute
            device_info = getattr(event, 'device_info', None)
            if device_info:
                store.dispatch(
                    ZigbeeDeviceInitializedEvent(
                        ieee=str(device_info.ieee),
                        manufacturer=device_info.manufacturer,
                        model=device_info.model,
                        name=getattr(device_info, 'name', None) or device_info.model,
                    ),
                    NotificationsAddAction(
                        notification=Notification(
                            title='Device Added',
                            content=f'{getattr(device_info, "name", None) or device_info.model} is ready',
                            display_type=NotificationDisplayType.FLASH,
                            color=SUCCESS_COLOR,
                            icon='󰔡',
                            # chime=Chime.ADD,
                        )
                    ),
                )
            # Refresh device list
            create_task(_refresh_devices(ZigbeeRefreshDevicesEvent()))

        _unsubscribe_pairing = _pairing_manager.subscribe_to_events(
            on_joined=on_device_joined,
            on_initialized=on_device_initialized,
        )

        await _pairing_manager.enable_pairing(event.duration)

        # Start countdown timer
        async def countdown() -> None:
            remaining = event.duration
            while remaining > 0:
                store.dispatch(
                    ZigbeeSetPairingStateAction(
                        is_pairing=True,
                        remaining_seconds=remaining,
                    )
                )
                await asyncio.sleep(1)
                remaining -= 1
            # Pairing ended
            store.dispatch(ZigbeeSetPairingStateAction(is_pairing=False))

        _pairing_task = create_task(countdown())

    except Exception:
        logger.exception('Failed to start pairing')
        store.dispatch(ZigbeeSetPairingStateAction(is_pairing=False))


async def _stop_pairing(_: ZigbeePairingStoppedEvent) -> None:
    """Disable pairing mode."""
    global _pairing_manager, _unsubscribe_pairing, _pairing_task

    if _pairing_task:
        _pairing_task.cancel()
        _pairing_task = None

    if _pairing_manager:
        try:
            await _pairing_manager.disable_pairing()
        except Exception:
            logger.exception('Error disabling pairing')

    if _unsubscribe_pairing:
        _unsubscribe_pairing()
        _unsubscribe_pairing = None


async def _toggle_entity(event: ZigbeeToggleEntityEvent) -> None:
    """Toggle a device entity."""
    manager = get_network_manager()
    if not manager.is_running:
        return

    device_info = manager.get_device_by_ieee(event.device_ieee)
    if not device_info:
        logger.warning('Device not found: %s', event.device_ieee)
        return

    device = device_info['device']
    entities = DeviceController.get_controllable_entities(device)

    for entity in entities:
        if entity.unique_id == event.entity_unique_id:
            try:
                await DeviceController.toggle(entity)
                logger.info('Toggled entity: %s', event.entity_unique_id)
                # Refresh device list so UI reflects new state
                await _refresh_devices(ZigbeeRefreshDevicesEvent())
            except Exception:
                logger.exception('Failed to toggle entity')
            break


async def _reset_network(_: ZigbeeResetNetworkEvent) -> None:
    """Reset the Zigbee network."""
    manager = get_network_manager()

    try:
        await manager.reset()
        store.dispatch(
            ZigbeeSetConnectionStateAction(state=ZigbeeConnectionState.DISCONNECTED),
            NotificationsAddAction(
                notification=Notification(
                    title='Network Reset',
                    content='Zigbee network has been reset',
                    display_type=NotificationDisplayType.FLASH,
                    color=WARNING_COLOR,
                    icon='󰜺',
                )
            ),
        )
    except Exception:
        logger.exception('Failed to reset network')
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Reset Failed',
                    content='Could not reset Zigbee network',
                    display_type=NotificationDisplayType.FLASH,
                    color=DANGER_COLOR,
                    icon='󰈅',
                )
            )
        )


async def _create_backup(_: ZigbeeCreateBackupEvent) -> None:
    """Create a network backup."""
    manager = get_network_manager()
    if not manager.is_running:
        return

    try:
        backup = await manager.create_backup()
        if backup:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Backup Created',
                        content=f'Backup with {backup["device_count"]} devices',
                        display_type=NotificationDisplayType.FLASH,
                        color=SUCCESS_COLOR,
                        icon='󰁯',
                        # chime=Chime.DONE,
                    )
                )
            )
            # Refresh backups list
            create_task(_refresh_devices(ZigbeeRefreshDevicesEvent()))
    except Exception:
        logger.exception('Failed to create backup')


async def _restore_backup(event: ZigbeeRestoreBackupEvent) -> None:
    """Restore from a backup."""
    manager = get_network_manager()
    if not manager.is_running:
        return

    try:
        await manager.restore_backup(event.backup_index)
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Backup Restored',
                    content='Network restored from backup',
                    display_type=NotificationDisplayType.FLASH,
                    color=SUCCESS_COLOR,
                    icon='󰁯',
                    # chime=Chime.DONE,
                )
            )
        )
        # Refresh devices after restore
        create_task(_refresh_devices(ZigbeeRefreshDevicesEvent()))
    except Exception:
        logger.exception('Failed to restore backup')
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Restore Failed',
                    content='Could not restore from backup',
                    display_type=NotificationDisplayType.FLASH,
                    color=DANGER_COLOR,
                    icon='󰈅',
                )
            )
        )


async def _delete_backup(event: ZigbeeDeleteBackupEvent) -> None:
    """Delete a backup."""
    manager = get_network_manager()
    if not manager.is_running:
        return

    try:
        manager.delete_backup(event.backup_index)
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Backup Deleted',
                    content='Backup has been removed',
                    display_type=NotificationDisplayType.FLASH,
                    color=WARNING_COLOR,
                    icon='󰆴',
                )
            )
        )
        # Refresh backups list
        create_task(_refresh_devices(ZigbeeRefreshDevicesEvent()))
    except Exception:
        logger.exception('Failed to delete backup')


def init_service() -> Subscriptions:
    """Initialize the Zigbee service."""
    # Register settings menu
    store.dispatch(
        RegisterSettingAppAction(
            priority=ZIGBEE_MENU_PRIORITY,
            category=SettingsCategory.NETWORK,
            menu_item=main_page.ZigbeeMainMenu,
        )
    )

    # Subscribe to events
    return [
        store.subscribe_event(ZigbeeDetectCoordinatorsEvent, _detect_coordinators),
        store.subscribe_event(ZigbeeConnectEvent, _connect_coordinator),
        store.subscribe_event(ZigbeeDisconnectEvent, _disconnect_coordinator),
        store.subscribe_event(ZigbeeRefreshDevicesEvent, _refresh_devices),
        store.subscribe_event(ZigbeePairingStartedEvent, _start_pairing),
        store.subscribe_event(ZigbeePairingStoppedEvent, _stop_pairing),
        store.subscribe_event(ZigbeeToggleEntityEvent, _toggle_entity),
        store.subscribe_event(ZigbeeResetNetworkEvent, _reset_network),
        store.subscribe_event(ZigbeeCreateBackupEvent, _create_backup),
        store.subscribe_event(ZigbeeRestoreBackupEvent, _restore_backup),
        store.subscribe_event(ZigbeeDeleteBackupEvent, _delete_backup),
    ]
