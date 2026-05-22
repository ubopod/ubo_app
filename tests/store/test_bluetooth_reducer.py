"""Tests for the Bluetooth service reducer.

The reducer turns refresh requests into ``BluetoothUpdateRequestEvent``s and
applies device-list updates, registering a status-bar icon that reflects the
adapter/connection state.

NOTE: The Bluetooth service uses bare imports (``from constants import ...``)
relative to its own directory, so the service path is added to ``sys.path``
before importing the reducer — same pattern as ``test_camera_reducer.py``.
Store types and the reducer are loaded together so the reducer's match-case
and the test's constructed actions reference the same class objects.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from redux import CompleteReducerResult, InitAction

from ubo_app.store.status_icons.types import StatusIconsRegisterAction

if TYPE_CHECKING:
    from collections.abc import Callable


def _import_store_types_and_reducer() -> tuple[Any, ...]:
    """Load Bluetooth store types, service constants, and the reducer."""
    modules_before = set(sys.modules)

    from ubo_app.store.services.bluetooth import (
        BluetoothDevice,
        BluetoothState,
        BluetoothUpdateAction,
        BluetoothUpdateRequestAction,
        BluetoothUpdateRequestEvent,
    )

    service_dir = str(
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '030-bluetooth',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from constants import (  # type: ignore[import-not-found]
        BLUETOOTH_CONNECTED_ICON,
        BLUETOOTH_ICON,
        BLUETOOTH_OFF_ICON,
        BLUETOOTH_STATE_ICON_ID,
    )
    from reducer import reducer  # type: ignore[import-not-found]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return (
        BluetoothDevice,
        BluetoothState,
        BluetoothUpdateAction,
        BluetoothUpdateRequestAction,
        BluetoothUpdateRequestEvent,
        BLUETOOTH_CONNECTED_ICON,
        BLUETOOTH_ICON,
        BLUETOOTH_OFF_ICON,
        BLUETOOTH_STATE_ICON_ID,
        reducer,
    )


(
    BluetoothDevice,
    BluetoothState,
    BluetoothUpdateAction,
    BluetoothUpdateRequestAction,
    BluetoothUpdateRequestEvent,
    BLUETOOTH_CONNECTED_ICON,
    BLUETOOTH_ICON,
    BLUETOOTH_OFF_ICON,
    BLUETOOTH_STATE_ICON_ID,
    reducer,
) = _import_store_types_and_reducer()

_reducer: Callable[..., Any] = reducer


def test_init_action_creates_initial_state() -> None:
    """InitAction yields an empty state and requests the first refresh."""
    result = _reducer(None, InitAction())

    assert isinstance(result, CompleteReducerResult)
    assert result.state == BluetoothState(
        is_powered=False,
        is_scanning=False,
        devices=None,
    )
    actions = list(result.actions or [])
    assert len(actions) == 1
    assert isinstance(actions[0], BluetoothUpdateRequestAction)


def test_update_request_action_emits_event() -> None:
    """A non-reset refresh request emits an event and keeps the state."""
    state = BluetoothState(is_powered=True, is_scanning=False, devices=[])
    result = _reducer(state, BluetoothUpdateRequestAction())

    assert isinstance(result, CompleteReducerResult)
    assert result.state is state
    events = list(result.events or [])
    assert len(events) == 1
    assert isinstance(events[0], BluetoothUpdateRequestEvent)


def test_update_request_action_with_reset_clears_devices() -> None:
    """A reset refresh request clears the device list to ``None``."""
    state = BluetoothState(
        is_powered=True,
        is_scanning=False,
        devices=[BluetoothDevice(address='AA:BB:CC:DD:EE:FF', name='Speaker')],
    )
    result = _reducer(state, BluetoothUpdateRequestAction(reset=True))

    assert isinstance(result, CompleteReducerResult)
    assert result.state.devices is None
    events = list(result.events or [])
    assert len(events) == 1
    assert isinstance(events[0], BluetoothUpdateRequestEvent)


def test_update_action_applies_devices_and_registers_icon() -> None:
    """An update applies the device list and registers the status icon."""
    state = BluetoothState(is_powered=False, is_scanning=False, devices=None)
    devices = [
        BluetoothDevice(
            address='AA:BB:CC:DD:EE:FF',
            name='Speaker',
            paired=True,
            connected=True,
        ),
    ]
    result = _reducer(
        state,
        BluetoothUpdateAction(devices=devices, is_powered=True, is_scanning=True),
    )

    assert isinstance(result, CompleteReducerResult)
    assert result.state.devices == devices
    assert result.state.is_powered is True
    assert result.state.is_scanning is True

    actions = list(result.actions or [])
    assert len(actions) == 1
    assert isinstance(actions[0], StatusIconsRegisterAction)
    assert actions[0].id == BLUETOOTH_STATE_ICON_ID
    assert actions[0].icon == BLUETOOTH_CONNECTED_ICON


def test_update_action_icon_reflects_adapter_and_connection_state() -> None:
    """The status icon distinguishes off, on, and connected states."""
    state = BluetoothState(is_powered=False, is_scanning=False, devices=None)

    def _icon_for(*, is_powered: bool, connected: bool) -> str:
        devices = [
            BluetoothDevice(
                address='AA:BB:CC:DD:EE:FF',
                name='Speaker',
                paired=True,
                connected=connected,
            ),
        ]
        result = _reducer(
            state,
            BluetoothUpdateAction(
                devices=devices,
                is_powered=is_powered,
                is_scanning=False,
            ),
        )
        assert isinstance(result, CompleteReducerResult)
        return next(iter(result.actions or [])).icon

    assert _icon_for(is_powered=False, connected=False) == BLUETOOTH_OFF_ICON
    assert _icon_for(is_powered=True, connected=False) == BLUETOOTH_ICON
    assert _icon_for(is_powered=True, connected=True) == BLUETOOTH_CONNECTED_ICON
