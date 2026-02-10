# ruff: noqa: D103
"""Reducer for the Zigbee service."""

from __future__ import annotations

from dataclasses import replace

from constants import ZIGBEE_STATE_ICON_ID, ZIGBEE_STATE_ICON_PRIORITY
from redux import (
    BaseAction,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.zigbee import (
    ZigbeeAction,
    ZigbeeConnectAction,
    ZigbeeConnectEvent,
    ZigbeeConnectionState,
    ZigbeeCreateBackupAction,
    ZigbeeCreateBackupEvent,
    ZigbeeDeleteBackupAction,
    ZigbeeDeleteBackupEvent,
    ZigbeeDetectCoordinatorsAction,
    ZigbeeDetectCoordinatorsEvent,
    ZigbeeDisconnectAction,
    ZigbeeDisconnectEvent,
    ZigbeeEvent,
    ZigbeePairingStartedEvent,
    ZigbeePairingStoppedEvent,
    ZigbeeRefreshDevicesAction,
    ZigbeeRefreshDevicesEvent,
    ZigbeeRemoveDeviceAction,
    ZigbeeResetNetworkAction,
    ZigbeeResetNetworkEvent,
    ZigbeeRestoreBackupAction,
    ZigbeeRestoreBackupEvent,
    ZigbeeSetConnectionStateAction,
    ZigbeeSetDetectingAction,
    ZigbeeSetPairingStateAction,
    ZigbeeStartPairingAction,
    ZigbeeState,
    ZigbeeStopPairingAction,
    ZigbeeToggleEntityAction,
    ZigbeeToggleEntityEvent,
    ZigbeeUpdateBackupsAction,
    ZigbeeUpdateCoordinatorsAction,
    ZigbeeUpdateDevicesAction,
    ZigbeeUpdateEntityStateAction,
)
from ubo_app.store.status_icons.types import StatusIconsRegisterAction


def _get_status_icon(state: ZigbeeConnectionState, *, is_pairing: bool) -> str:
    """Get the appropriate status icon based on connection state."""
    if is_pairing:
        return '󰐕'  # Pairing mode
    return {
        ZigbeeConnectionState.CONNECTED: '󰛁',  # Connected
        ZigbeeConnectionState.CONNECTING: '󱘖',  # Connecting
        ZigbeeConnectionState.DISCONNECTED: '󰛀',  # Disconnected
        ZigbeeConnectionState.ERROR: '󰈅',  # Error
    }[state]


def reducer(
    state: ZigbeeState | None,
    action: ZigbeeAction,
) -> ReducerResult[ZigbeeState, BaseAction, ZigbeeEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return ZigbeeState()
        raise InitializationActionError(action)

    match action:
        # Coordinator detection
        case ZigbeeDetectCoordinatorsAction():
            return CompleteReducerResult(
                state=replace(state, is_detecting=True, coordinators=None),
                events=[ZigbeeDetectCoordinatorsEvent()],
            )

        case ZigbeeSetDetectingAction():
            return replace(state, is_detecting=action.is_detecting)

        case ZigbeeUpdateCoordinatorsAction():
            return replace(
                state,
                coordinators=action.coordinators,
                is_detecting=False,
            )

        # Connection management
        case ZigbeeConnectAction():
            # Skip if already connecting or already connected to this coordinator
            if state.connection_state == ZigbeeConnectionState.CONNECTING:
                return state
            if (
                state.connection_state == ZigbeeConnectionState.CONNECTED
                and state.current_coordinator
                and state.current_coordinator.port == action.coordinator.port
            ):
                return state
            return CompleteReducerResult(
                state=replace(
                    state,
                    connection_state=ZigbeeConnectionState.CONNECTING,
                ),
                events=[ZigbeeConnectEvent(coordinator=action.coordinator)],
            )

        case ZigbeeDisconnectAction():
            return CompleteReducerResult(
                state=replace(
                    state,
                    connection_state=ZigbeeConnectionState.DISCONNECTED,
                    current_coordinator=None,
                    devices=None,
                    backups=None,
                ),
                events=[ZigbeeDisconnectEvent()],
            )

        case ZigbeeSetConnectionStateAction():
            new_state = replace(
                state,
                connection_state=action.state,
                current_coordinator=action.coordinator or state.current_coordinator,
            )
            actions: list[BaseAction] = []
            events: list[ZigbeeEvent] = []

            # Update status icon when connected
            if action.state == ZigbeeConnectionState.CONNECTED:
                actions.append(
                    StatusIconsRegisterAction(
                        icon=_get_status_icon(
                            action.state, is_pairing=state.is_pairing,
                        ),
                        priority=ZIGBEE_STATE_ICON_PRIORITY,
                        id=ZIGBEE_STATE_ICON_ID,
                    ),
                )
                # Request device refresh on connection
                events.append(ZigbeeRefreshDevicesEvent())

            return CompleteReducerResult(
                state=new_state,
                actions=actions,
                events=events,
            )

        # Device management
        case ZigbeeRefreshDevicesAction():
            return CompleteReducerResult(
                state=state,
                events=[ZigbeeRefreshDevicesEvent()],
            )

        case ZigbeeUpdateDevicesAction():
            return replace(state, devices=action.devices)

        case ZigbeeUpdateEntityStateAction():
            if not state.devices:
                return state
            new_devices = list(state.devices)
            for i, device in enumerate(new_devices):
                if device.ieee != action.device_ieee:
                    continue
                new_entities = list(device.entities)
                for j, entity in enumerate(new_entities):
                    if entity.unique_id == action.entity_unique_id:
                        new_entities[j] = replace(
                            entity,
                            state_display=action.state_display,
                            is_on=action.is_on,
                        )
                        break
                new_devices[i] = replace(device, entities=tuple(new_entities))
                break
            return replace(state, devices=tuple(new_devices))

        # Pairing
        case ZigbeeStartPairingAction():
            return CompleteReducerResult(
                state=replace(
                    state,
                    is_pairing=True,
                    pairing_remaining_seconds=action.duration,
                ),
                events=[ZigbeePairingStartedEvent(duration=action.duration)],
                actions=[
                    StatusIconsRegisterAction(
                        icon=_get_status_icon(state.connection_state, is_pairing=True),
                        priority=ZIGBEE_STATE_ICON_PRIORITY,
                        id=ZIGBEE_STATE_ICON_ID,
                    ),
                ],
            )

        case ZigbeeStopPairingAction():
            return CompleteReducerResult(
                state=replace(
                    state,
                    is_pairing=False,
                    pairing_remaining_seconds=0,
                ),
                events=[ZigbeePairingStoppedEvent()],
                actions=[
                    StatusIconsRegisterAction(
                        icon=_get_status_icon(state.connection_state, is_pairing=False),
                        priority=ZIGBEE_STATE_ICON_PRIORITY,
                        id=ZIGBEE_STATE_ICON_ID,
                    ),
                ],
            )

        case ZigbeeSetPairingStateAction():
            return replace(
                state,
                is_pairing=action.is_pairing,
                pairing_remaining_seconds=action.remaining_seconds,
            )

        # Entity control
        case ZigbeeToggleEntityAction():
            new_state = state
            if state.devices:
                new_devices = list(state.devices)
                for i, device in enumerate(new_devices):
                    if device.ieee != action.device_ieee:
                        continue
                    new_entities = list(device.entities)
                    for j, entity in enumerate(new_entities):
                        if (
                            entity.unique_id == action.entity_unique_id
                            and entity.is_on is not None
                        ):
                            new_entities[j] = replace(
                                entity, is_on=not entity.is_on,
                            )
                            break
                    new_devices[i] = replace(
                        device, entities=tuple(new_entities),
                    )
                    break
                new_state = replace(state, devices=tuple(new_devices))
            return CompleteReducerResult(
                state=new_state,
                events=[
                    ZigbeeToggleEntityEvent(
                        device_ieee=action.device_ieee,
                        entity_unique_id=action.entity_unique_id,
                    ),
                ],
            )

        # Device operations
        case ZigbeeRemoveDeviceAction():
            # Just dispatch event, actual removal handled by event handler
            return state

        # Network reset
        case ZigbeeResetNetworkAction():
            return CompleteReducerResult(
                state=state,
                events=[ZigbeeResetNetworkEvent()],
            )

        # Backup management
        case ZigbeeUpdateBackupsAction():
            return replace(state, backups=action.backups)

        case ZigbeeCreateBackupAction():
            return CompleteReducerResult(
                state=state,
                events=[ZigbeeCreateBackupEvent()],
            )

        case ZigbeeRestoreBackupAction():
            return CompleteReducerResult(
                state=state,
                events=[ZigbeeRestoreBackupEvent(backup_index=action.backup_index)],
            )

        case ZigbeeDeleteBackupAction():
            return CompleteReducerResult(
                state=state,
                events=[ZigbeeDeleteBackupEvent(backup_index=action.backup_index)],
            )

        case _:
            return state

    return state
