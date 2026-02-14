"""Zigbee service state types, actions, and events."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Sequence


class ZigbeeEntityPlatform(StrEnum):
    """Platform types for Zigbee entities."""

    SWITCH = 'switch'
    LIGHT = 'light'
    BINARY_SENSOR = 'binary_sensor'
    SENSOR = 'sensor'
    DEVICE_TRACKER = 'device_tracker'
    EVENT = 'event'
    OTHER = 'other'


class ZigbeeConnectionState(StrEnum):
    """Connection state of the Zigbee coordinator."""

    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    ERROR = 'error'


class ZigbeeCoordinator(Immutable):
    """Represents a detected Zigbee coordinator."""

    port: str
    description: str
    radio_type: str  # RadioType name as string for serialization
    baudrate: int
    name: str | None = None
    has_network: bool = False


class ZigbeeEntity(Immutable):
    """Represents a controllable or monitorable entity."""

    unique_id: str
    platform: ZigbeeEntityPlatform
    display_name: str
    device_ieee: str
    state_display: str
    is_on: bool | None = None
    is_controllable: bool = False


class ZigbeeDevice(Immutable):
    """Represents a paired Zigbee device."""

    ieee: str
    nwk: int
    manufacturer: str | None
    model: str | None
    name: str
    custom_name: str | None
    available: bool
    location: str | None = None
    entities: Sequence[ZigbeeEntity] = ()


class ZigbeeBackup(Immutable):
    """Represents a network backup."""

    index: int
    backup_time: str
    device_count: int
    is_complete: bool


# Actions


class ZigbeeAction(BaseAction):
    """Base class for Zigbee actions."""


class ZigbeeDetectCoordinatorsAction(ZigbeeAction):
    """Trigger coordinator detection scan."""


class ZigbeeSetDetectingAction(ZigbeeAction):
    """Set the detecting state."""

    is_detecting: bool


class ZigbeeUpdateCoordinatorsAction(ZigbeeAction):
    """Update the list of detected coordinators."""

    coordinators: Sequence[ZigbeeCoordinator]


class ZigbeeConnectAction(ZigbeeAction):
    """Connect to a coordinator."""

    coordinator: ZigbeeCoordinator


class ZigbeeDisconnectAction(ZigbeeAction):
    """Disconnect from current coordinator."""


class ZigbeeSetConnectionStateAction(ZigbeeAction):
    """Set the connection state."""

    state: ZigbeeConnectionState
    coordinator: ZigbeeCoordinator | None = None


class ZigbeeRefreshDevicesAction(ZigbeeAction):
    """Trigger a device list refresh."""


class ZigbeeUpdateDevicesAction(ZigbeeAction):
    """Update the device list."""

    devices: Sequence[ZigbeeDevice]


class ZigbeeStartPairingAction(ZigbeeAction):
    """Enable pairing mode."""

    duration: int = 60


class ZigbeeStopPairingAction(ZigbeeAction):
    """Disable pairing mode."""


class ZigbeeSetPairingStateAction(ZigbeeAction):
    """Set pairing state."""

    is_pairing: bool
    remaining_seconds: int = 0


class ZigbeeSetJoiningDeviceAction(ZigbeeAction):
    """Set the name of a device currently joining/initializing."""

    device_name: str | None = None
    device_ieee: str | None = None


class ZigbeeUpdateEntityStateAction(ZigbeeAction):
    """Update entity state from ZHA STATE_CHANGED event."""

    device_ieee: str
    entity_unique_id: str
    state_display: str
    is_on: bool | None = None


class ZigbeeToggleEntityAction(ZigbeeAction):
    """Toggle a switch/light entity."""

    device_ieee: str
    entity_unique_id: str


class ZigbeeInteractEntityAction(ZigbeeAction):
    """Smart action: toggles controllable entities, reads sensors aloud."""

    device_ieee: str
    entity_unique_id: str


class ZigbeeRenameDeviceAction(ZigbeeAction):
    """Rename a device."""

    device_ieee: str
    name: str


class ZigbeeRemoveDeviceAction(ZigbeeAction):
    """Remove a device from the network."""

    device_ieee: str


class ZigbeeRenameCoordinatorAction(ZigbeeAction):
    """Rename a coordinator."""

    port: str
    name: str


class ZigbeeResetNetworkAction(ZigbeeAction):
    """Reset the Zigbee network (deletes all devices)."""


class ZigbeeUpdateBackupsAction(ZigbeeAction):
    """Update the backup list."""

    backups: Sequence[ZigbeeBackup]


class ZigbeeCreateBackupAction(ZigbeeAction):
    """Create a new backup."""


class ZigbeeRestoreBackupAction(ZigbeeAction):
    """Restore from a backup."""

    backup_index: int


class ZigbeeDeleteBackupAction(ZigbeeAction):
    """Delete a backup."""

    backup_index: int


# Events


class ZigbeeEvent(BaseEvent):
    """Base class for Zigbee events."""


class ZigbeeDetectCoordinatorsEvent(ZigbeeEvent):
    """Triggered to start coordinator detection."""


class ZigbeeConnectEvent(ZigbeeEvent):
    """Triggered to connect to a coordinator."""

    coordinator: ZigbeeCoordinator


class ZigbeeDisconnectEvent(ZigbeeEvent):
    """Triggered to disconnect from coordinator."""


class ZigbeeDeviceJoinedEvent(ZigbeeEvent):
    """Emitted when a device joins during pairing."""

    ieee: str
    nwk: int


class ZigbeeDeviceInitializedEvent(ZigbeeEvent):
    """Emitted when a device is fully initialized after pairing."""

    ieee: str
    manufacturer: str | None
    model: str | None
    name: str


class ZigbeePairingStartedEvent(ZigbeeEvent):
    """Emitted when pairing mode is enabled."""

    duration: int


class ZigbeePairingStoppedEvent(ZigbeeEvent):
    """Emitted when pairing mode ends."""


class ZigbeeRefreshDevicesEvent(ZigbeeEvent):
    """Triggered to refresh device list."""


class ZigbeeToggleEntityEvent(ZigbeeEvent):
    """Triggered to toggle an entity."""

    device_ieee: str
    entity_unique_id: str


class ZigbeeResetNetworkEvent(ZigbeeEvent):
    """Triggered to reset the network."""


class ZigbeeCreateBackupEvent(ZigbeeEvent):
    """Triggered to create a backup."""


class ZigbeeRestoreBackupEvent(ZigbeeEvent):
    """Triggered to restore a backup."""

    backup_index: int


class ZigbeeDeleteBackupEvent(ZigbeeEvent):
    """Triggered to delete a backup."""

    backup_index: int


# State


class ZigbeeState(Immutable):
    """State for the Zigbee service."""

    connection_state: ZigbeeConnectionState = ZigbeeConnectionState.DISCONNECTED
    coordinators: Sequence[ZigbeeCoordinator] | None = None
    current_coordinator: ZigbeeCoordinator | None = None
    devices: Sequence[ZigbeeDevice] | None = None
    backups: Sequence[ZigbeeBackup] | None = None
    is_detecting: bool = False
    is_pairing: bool = False
    pairing_remaining_seconds: int = 0
    joining_device_name: str | None = None
    joining_device_ieee: str | None = None
