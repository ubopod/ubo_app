"""Tests for the sensors reducer.

Covers the legacy status-bar arms (``SensorsReportReadingAction`` →
``state.temperature`` / ``state.light``, which the status bar depends on via
``register_status_bar_dependency``) alongside the device-registry arms added
for the Home Assistant integration.

NOTE: the sensors service lives under ``ubo_app/services/040-sensors``, which
is not an importable package path, so we add the service directory to
``sys.path`` before importing the reducer — same pattern as
``test_camera_reducer.py``. The store types are loaded inside the same loader
so the reducer's match-case and the test's constructed actions always
reference the *same* class objects, even if an integration test in between
has cleared ``sys.modules``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from redux import CompleteReducerResult, InitAction, InitializationActionError

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.services.sensors import (
        SensorDeviceState,
        SensorsState,
        SensorStatus,
    )


def _import_store_types_and_reducer() -> tuple[Any, Callable[..., Any]]:
    modules_before = set(sys.modules)

    from ubo_app.store.services import sensors as sensors_types

    service_dir = str(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # type: ignore[import-not-found]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return sensors_types, reducer


types, reducer = _import_store_types_and_reducer()


def _device(
    *,
    definition_id: str = 'bme280',
    address: int = 0x76,
    status: SensorStatus | None = None,
) -> SensorDeviceState:
    return types.SensorDeviceState(
        id=f'{definition_id}_{address:#04x}',
        definition_id=definition_id,
        label=definition_id.upper(),
        address=address,
        is_builtin=False,
        status=status or types.SensorStatus.ACTIVE,
    )


def _state() -> SensorsState:
    state = reducer(None, InitAction())
    assert isinstance(state, types.SensorsState)
    return state


def test_none_state_without_init_raises() -> None:
    """A non-init action against a `None` state is an initialization error."""
    with pytest.raises(InitializationActionError):
        reducer(None, types.SensorsScanAction())


def test_init_produces_empty_registry() -> None:
    """`InitAction` yields an empty device registry and the legacy null readings."""
    state = _state()

    assert state.devices == {}
    assert state.is_scanning is False
    assert state.temperature.value is None
    assert state.light.value is None


def test_legacy_reading_actions_still_feed_the_status_bar() -> None:
    """The pre-existing temperature/light arms are untouched by the new fields."""
    state = _state()

    state = reducer(
        state,
        types.SensorsReportReadingAction(
            sensor=types.Sensor.TEMPERATURE,
            reading=21.5,
            timestamp=0.0,
        ),
    )
    state = reducer(
        state,
        types.SensorsReportReadingAction(
            sensor=types.Sensor.LIGHT,
            reading=317.0,
            timestamp=0.0,
        ),
    )

    assert state.temperature.value == 21.5
    assert state.light.value == 317.0


def test_scan_action_sets_flag_and_emits_event() -> None:
    """`SensorsScanAction` flips `is_scanning` and emits the scan event."""
    result = reducer(_state(), types.SensorsScanAction())

    assert isinstance(result, CompleteReducerResult)
    assert result.state.is_scanning is True
    assert result.events is not None
    assert [type(event) for event in result.events] == [types.SensorsScanEvent]


def test_scan_completed_replaces_the_device_registry() -> None:
    """A completed scan is authoritative: it replaces, not merges, the registry."""
    result = reducer(_state(), types.SensorsScanAction())
    assert isinstance(result, CompleteReducerResult)

    device = _device()
    state = reducer(
        result.state,
        types.SensorsScanCompletedAction(devices=(device,)),
    )

    assert state.is_scanning is False
    assert state.devices == {device.id: device}

    # A subsequent scan that no longer sees the device drops it — an unplugged
    # sensor must not linger in the registry.
    state = reducer(state, types.SensorsScanCompletedAction(devices=()))
    assert state.devices == {}


def test_readings_update_only_the_named_device() -> None:
    """Readings land on one device and leave its identity fields intact."""
    first = _device(definition_id='bme280', address=0x76)
    second = _device(definition_id='sht4x', address=0x44)
    state = reducer(
        _state(),
        types.SensorsScanCompletedAction(devices=(first, second)),
    )

    entities = (types.SensorEntityReading(key='temperature', value=22.0),)
    state = reducer(
        state,
        types.SensorsReportDeviceReadingsAction(
            device_id=first.id,
            entities=entities,
            timestamp=0.0,
        ),
    )

    assert state.devices[first.id].entities == entities
    assert state.devices[second.id].entities == ()
    # Identity fields survive a reading update — both the persistence selector
    # and the menu's identity projection depend on this.
    assert state.devices[first.id].address == 0x76
    assert state.devices[first.id].definition_id == 'bme280'
    assert state.devices[first.id].status is types.SensorStatus.ACTIVE


def test_readings_for_an_unknown_device_are_ignored() -> None:
    """A reading racing a re-scan that dropped its device is a no-op, not a crash."""
    state = reducer(
        _state(),
        types.SensorsReportDeviceReadingsAction(
            device_id='ghost_0x76',
            entities=(types.SensorEntityReading(key='temperature', value=1.0),),
            timestamp=0.0,
        ),
    )

    assert state.devices == {}


def test_a_failed_scan_keeps_the_devices_it_could_not_re_confirm() -> None:
    """`devices=None` is a failure, not an empty bus.

    Treating an I²C error as "nothing found" would clear the registry, retire
    every Home Assistant entity and persist the loss — on a transient EIO,
    while the sensors are still plugged in and still being read.
    """
    device = _device()
    state = reducer(
        _state(),
        types.SensorsScanCompletedAction(devices=(device,)),
    )

    result = reducer(
        reducer(state, types.SensorsScanAction()).state,
        types.SensorsScanCompletedAction(),
    )

    assert result.devices == {device.id: device}
    # Still cleared, or Refresh would be inert until a reboot.
    assert result.is_scanning is False
