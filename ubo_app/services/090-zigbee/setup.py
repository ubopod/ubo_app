# ruff: noqa: PLW0602, PLW0603
"""Setup and initialization for the Zigbee service."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from constants import ZIGBEE_MENU_PRIORITY
from pages import main as main_page
from zha.application.const import RadioType
from zigbee import (
    DeviceController,
    DevicePairingManager,
    NetworkManager,
    discover_coordinators,
)

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuGoBackAction,
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
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
    ZigbeeDetectCoordinatorsAction,
    ZigbeeDetectCoordinatorsEvent,
    ZigbeeDevice,
    ZigbeeDisconnectEvent,
    ZigbeeEntity,
    ZigbeeEntityPlatform,
    ZigbeePairingStartedEvent,
    ZigbeePairingStoppedEvent,
    ZigbeeRefreshDevicesEvent,
    ZigbeeResetNetworkEvent,
    ZigbeeRestoreBackupEvent,
    ZigbeeSetConnectionStateAction,
    ZigbeeSetDetectingAction,
    ZigbeeSetJoiningDeviceAction,
    ZigbeeSetPairingStateAction,
    ZigbeeStopPairingAction,
    ZigbeeToggleEntityEvent,
    ZigbeeUpdateBackupsAction,
    ZigbeeUpdateCoordinatorsAction,
    ZigbeeUpdateDevicesAction,
    ZigbeeUpdateEntityStateAction,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Callable

    from zha.application import Platform
    from zha.application.platforms import PlatformEntity

    from ubo_app.utils.types import Subscriptions

# Global network manager instance
_network_manager: NetworkManager | None = None
_pairing_manager: DevicePairingManager | None = None
_pairing_task: asyncio.Handle | None = None
_unsubscribe_pairing: Callable[[], None] | None = None
_pairing_active: bool = False
_entity_unsubs: dict[str, Callable[[], None]] = {}
_connection_lost_unsub: Callable[[], None] | None = None

# Platform mapping from ZHA Platform enum to store ZigbeeEntityPlatform
_PLATFORM_MAP: dict[str, ZigbeeEntityPlatform] = {
    'switch': ZigbeeEntityPlatform.SWITCH,
    'light': ZigbeeEntityPlatform.LIGHT,
    'binary_sensor': ZigbeeEntityPlatform.BINARY_SENSOR,
    'sensor': ZigbeeEntityPlatform.SENSOR,
    'device_tracker': ZigbeeEntityPlatform.DEVICE_TRACKER,
    'event': ZigbeeEntityPlatform.EVENT,
}


def _map_platform(platform: Platform) -> ZigbeeEntityPlatform:
    """Map a ZHA Platform enum value to ZigbeeEntityPlatform."""
    return _PLATFORM_MAP.get(platform.value, ZigbeeEntityPlatform.OTHER)


def _unsubscribe_all_entities() -> None:
    """Unsubscribe from all entity STATE_CHANGED events."""
    global _entity_unsubs
    for unsub in _entity_unsubs.values():
        unsub()
    _entity_unsubs.clear()


def _subscribe_entity_events() -> None:
    """Subscribe to STATE_CHANGED events for all entities on all devices."""
    from zha.const import STATE_CHANGED
    from zigbee.device_control import CONTROLLABLE_PLATFORMS

    _unsubscribe_all_entities()

    manager = get_network_manager()
    if not manager.is_running or manager.gateway is None:
        return

    for device in manager.gateway.devices.values():
        if device.is_coordinator:
            continue
        device_ieee = str(device.ieee)
        for (_platform, _uid), entity in device.platform_entities.items():

            def _make_callback(
                ent: PlatformEntity,
                ieee: str,
                plat: Platform,
            ) -> Callable[[object], None]:
                def _on_state_changed(_event: object) -> None:
                    state_display = DeviceController.format_entity_state(ent)
                    is_on = None
                    if plat in CONTROLLABLE_PLATFORMS:
                        state = ent.state
                        is_on = (
                            state.get('state')
                            if 'state' in state
                            else state.get('on', False)
                        )
                    logger.debug(
                        'Entity state changed: ieee=%s uid=%s is_on=%s display=%s',
                        ieee,
                        ent.unique_id,
                        is_on,
                        state_display,
                    )
                    store.dispatch(
                        ZigbeeUpdateEntityStateAction(
                            device_ieee=ieee,
                            entity_unique_id=ent.unique_id,
                            state_display=state_display,
                            is_on=is_on,
                        ),
                    )

                return _on_state_changed

            callback = _make_callback(entity, device_ieee, _platform)
            unsub = entity.on_event(STATE_CHANGED, callback)
            _entity_unsubs[entity.unique_id] = unsub


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
                    {
                        'port': c.port,
                        'description': c.description,
                        'radio_type': c.radio_type,
                    }
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
                ),
            ),
        )


def _on_connection_lost(_event: object) -> None:
    """Handle unexpected connection loss from the radio."""
    global _connection_lost_unsub, _pairing_manager

    logger.warning('Zigbee radio connection lost')

    _unsubscribe_all_entities()
    _connection_lost_unsub = None

    # Clean up pairing state
    _cleanup_pairing_state()
    _pairing_manager = None

    # Shut down gateway asynchronously (catches exceptions, always cleans up)
    async def _shutdown_gateway() -> None:
        try:
            await get_network_manager().shutdown()
        except Exception:
            logger.exception('Error during post-disconnect shutdown')

    create_task(_shutdown_gateway())

    # The connection_menu autorun uses AutorunOptions(default_value=None) and
    # returns None for DISCONNECTED, so it never fires — no race with
    # MenuGoBackAction's _pop(). Safe to dispatch directly from any thread.
    store.dispatch(
        ZigbeeSetConnectionStateAction(
            state=ZigbeeConnectionState.DISCONNECTED,
        ),
        ZigbeeDetectCoordinatorsAction(),
        MenuGoBackAction(),
        NotificationsAddAction(
            notification=Notification(
                title='Connection Lost',
                content='Zigbee coordinator disconnected unexpectedly',
                display_type=NotificationDisplayType.STICKY,
                color=DANGER_COLOR,
                icon='󰈅',
            ),
        ),
    )


async def _connect_coordinator(event: ZigbeeConnectEvent) -> None:
    """Handle coordinator connection request."""
    from zigbee.coordinator_probe import DetectedCoordinator as DetectedCoord

    global _connection_lost_unsub

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

        # Subscribe to connection loss events from the gateway
        if manager.gateway is not None:
            _connection_lost_unsub = manager.gateway.on_event(
                'connection_lost', _on_connection_lost,
            )

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
                ),
            ),
        )


async def _disconnect_coordinator(_: ZigbeeDisconnectEvent) -> None:
    """Handle coordinator disconnection request."""
    logger.info('Disconnecting from coordinator')
    manager = get_network_manager()
    global _pairing_manager, _unsubscribe_pairing, _connection_lost_unsub

    # Clean up entity subscriptions
    _unsubscribe_all_entities()

    # Clean up connection loss listener
    if _connection_lost_unsub:
        _connection_lost_unsub()
        _connection_lost_unsub = None

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
    from zigbee.device_control import CONTROLLABLE_PLATFORMS

    manager = get_network_manager()
    if not manager.is_running:
        return

    try:
        raw_devices = manager.get_devices()
        devices = []
        for dev in raw_devices:
            # Build entities from platform_entities
            entities: list[ZigbeeEntity] = []
            zha_device = dev.get('device')
            if zha_device and hasattr(zha_device, 'platform_entities'):
                for (platform, _uid), entity in zha_device.platform_entities.items():
                    is_controllable = platform in CONTROLLABLE_PLATFORMS
                    is_on = None
                    if is_controllable:
                        state = entity.state
                        is_on = (
                            state.get('state')
                            if 'state' in state
                            else state.get('on', False)
                        )
                    entities.append(
                        ZigbeeEntity(
                            unique_id=entity.unique_id,
                            platform=_map_platform(platform),
                            display_name=DeviceController.get_display_name(entity),
                            device_ieee=str(dev['ieee']),
                            state_display=DeviceController.format_entity_state(entity),
                            is_on=is_on,
                            is_controllable=is_controllable,
                        ),
                    )

            devices.append(
                ZigbeeDevice(
                    ieee=str(dev['ieee']),
                    nwk=dev['nwk'],
                    manufacturer=dev['manufacturer'],
                    model=dev['model'],
                    name=dev['name'],
                    custom_name=dev['custom_name'],
                    available=dev['available'],
                    location=dev.get('location'),
                    entities=tuple(entities),
                ),
            )
        store.dispatch(ZigbeeUpdateDevicesAction(devices=devices))

        # Subscribe to entity state changes
        _subscribe_entity_events()

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


def _cleanup_pairing_state() -> None:
    """Clean up leftover pairing state from a previous session."""
    global _unsubscribe_pairing, _pairing_task, _pairing_active

    _pairing_active = False
    if _unsubscribe_pairing:
        logger.debug('Cleaning up previous pairing event subscriptions')
        _unsubscribe_pairing()
        _unsubscribe_pairing = None
    if _pairing_task:
        _pairing_task.cancel()
        _pairing_task = None


def _on_device_joined(event: object) -> None:
    """Handle a device joining during pairing."""
    logger.info('Device joined: %s', event)
    ieee = getattr(event, 'ieee', None)
    nwk = getattr(event, 'nwk', None)
    device_ieee = str(ieee) if ieee is not None else None
    store.dispatch(
        ZigbeeSetJoiningDeviceAction(
            device_name='New device',
            device_ieee=device_ieee,
        ),
    )
    if ieee is not None and nwk is not None:
        logger.info('Device joined: ieee=%s nwk=%s', ieee, nwk)


def _on_device_initialized(event: object) -> None:
    """Handle a device completing initialization during pairing."""
    global _pairing_active
    logger.info('Device initialized: %s', event)
    device_info = getattr(event, 'device_info', None)
    device_name = None
    if device_info:
        device_name = getattr(device_info, 'name', None) or device_info.model
        device_ieee = str(getattr(device_info, 'ieee', '')) or None
        store.dispatch(
            ZigbeeSetJoiningDeviceAction(
                device_name=device_name,
                device_ieee=device_ieee,
            ),
        )

    if not _pairing_active:
        return
    # Prevent duplicate _finish_pairing tasks (event fires twice per device)
    _pairing_active = False

    async def _finish_pairing() -> None:
        logger.info('Finishing pairing: refreshing devices then stopping')
        try:
            await _refresh_devices(ZigbeeRefreshDevicesEvent())
        except Exception:
            logger.exception('Error refreshing devices after pairing')
        logger.info('Dispatching ZigbeeStopPairingAction')
        store.dispatch(ZigbeeStopPairingAction())

    create_task(_finish_pairing())


async def _start_pairing(event: ZigbeePairingStartedEvent) -> None:
    """Enable pairing mode on the coordinator."""
    global _pairing_manager, _unsubscribe_pairing, _pairing_task, _pairing_active

    manager = get_network_manager()
    if not manager.is_running or manager.gateway is None:
        logger.warning('Cannot start pairing: network not running')
        store.dispatch(ZigbeeSetPairingStateAction(is_pairing=False))
        return

    _cleanup_pairing_state()

    try:
        _pairing_manager = DevicePairingManager(manager.gateway)
        _unsubscribe_pairing = _pairing_manager.subscribe_to_events(
            on_joined=_on_device_joined,
            on_initialized=_on_device_initialized,
        )

        logger.info('Enabling pairing for %d seconds', event.duration)
        await _pairing_manager.enable_pairing(event.duration)
        _pairing_active = True

        # Start countdown timer — checks _pairing_active flag each tick
        # because create_task returns asyncio.Handle whose cancel() does NOT
        # stop the running coroutine.
        async def countdown() -> None:
            remaining = event.duration
            while remaining > 0 and _pairing_active:
                store.dispatch(
                    ZigbeeSetPairingStateAction(
                        is_pairing=True,
                        remaining_seconds=remaining,
                    ),
                )
                await asyncio.sleep(1)
                remaining -= 1
            if _pairing_active:
                logger.info('Pairing countdown expired, stopping pairing')
                store.dispatch(
                    ZigbeeStopPairingAction(),
                    ZigbeeSetJoiningDeviceAction(device_name=None),
                )

        _pairing_task = create_task(countdown())

    except Exception:
        logger.exception('Failed to start pairing')
        _pairing_active = False
        store.dispatch(ZigbeeSetPairingStateAction(is_pairing=False))


async def _stop_pairing(_: ZigbeePairingStoppedEvent) -> None:
    """Disable pairing mode."""
    global _pairing_manager, _unsubscribe_pairing, _pairing_task, _pairing_active

    logger.info('Stopping pairing: cleaning up resources')

    # Signal countdown coroutine to exit (Handle.cancel doesn't stop coroutines)
    _pairing_active = False

    if _pairing_task:
        logger.debug('Cancelling pairing countdown task')
        _pairing_task.cancel()
        _pairing_task = None

    if _pairing_manager:
        try:
            await _pairing_manager.disable_pairing()
        except Exception:
            logger.exception('Error disabling pairing')
        _pairing_manager = None

    if _unsubscribe_pairing:
        logger.debug('Unsubscribing from pairing events')
        _unsubscribe_pairing()
        _unsubscribe_pairing = None

    logger.info('Pairing stopped and cleaned up')


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
            except Exception:
                if not manager.is_running:
                    logger.debug('Toggle aborted: network no longer running')
                else:
                    logger.exception('Failed to toggle entity')
            break


async def _reset_network(_: ZigbeeResetNetworkEvent) -> None:
    """Reset the Zigbee network."""
    manager = get_network_manager()

    try:
        await manager.reset()
        store.dispatch(
            ZigbeeSetConnectionStateAction(state=ZigbeeConnectionState.DISCONNECTED),
            ZigbeeDetectCoordinatorsAction(),
            MenuGoBackAction(),
            NotificationsAddAction(
                notification=Notification(
                    title='Network Reset',
                    content='Zigbee network has been reset',
                    display_type=NotificationDisplayType.FLASH,
                    color=WARNING_COLOR,
                    icon='󰜺',
                ),
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
                ),
            ),
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
                    ),
                ),
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
                ),
            ),
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
                ),
            ),
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
                ),
            ),
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
        ),
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
