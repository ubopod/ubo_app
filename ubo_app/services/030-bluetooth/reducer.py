# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from constants import (
    BLUETOOTH_CONNECTED_ICON,
    BLUETOOTH_ICON,
    BLUETOOTH_OFF_ICON,
    BLUETOOTH_STATE_ICON_ID,
    BLUETOOTH_STATE_ICON_PRIORITY,
)
from redux import (
    BaseAction,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.bluetooth import (
    BluetoothAction,
    BluetoothEvent,
    BluetoothState,
    BluetoothUpdateAction,
    BluetoothUpdateRequestAction,
    BluetoothUpdateRequestEvent,
)
from ubo_app.store.status_icons.types import StatusIconsRegisterAction


def _state_icon(*, is_powered: bool, is_connected: bool) -> str:
    if not is_powered:
        return BLUETOOTH_OFF_ICON
    if is_connected:
        return BLUETOOTH_CONNECTED_ICON
    return BLUETOOTH_ICON


def reducer(
    state: BluetoothState | None,
    action: BluetoothAction,
) -> ReducerResult[BluetoothState, BaseAction, BluetoothEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return CompleteReducerResult(
                state=BluetoothState(
                    is_powered=False,
                    is_scanning=False,
                    devices=None,
                ),
                actions=[BluetoothUpdateRequestAction()],
            )
        raise InitializationActionError(action)

    match action:
        case BluetoothUpdateRequestAction():
            return CompleteReducerResult(
                state=replace(state, devices=None) if action.reset else state,
                events=[BluetoothUpdateRequestEvent()],
            )

        case BluetoothUpdateAction():
            return CompleteReducerResult(
                state=replace(
                    state,
                    devices=action.devices,
                    is_powered=action.is_powered,
                    is_scanning=action.is_scanning,
                ),
                actions=[
                    StatusIconsRegisterAction(
                        icon=_state_icon(
                            is_powered=action.is_powered,
                            is_connected=any(
                                device.connected for device in action.devices
                            ),
                        ),
                        priority=BLUETOOTH_STATE_ICON_PRIORITY,
                        id=BLUETOOTH_STATE_ICON_ID,
                    ),
                ],
            )

        case _:
            return state

    return state
