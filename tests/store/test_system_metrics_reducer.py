"""Tests for the system-metrics reducer.

Covers the widened `SystemMetricsUpdateAction` (CPU temperature, load average,
boot time and network rates) and the separate `SystemStorageUpdateAction`,
which runs on a slower loop and must not disturb the fast-moving fields.

NOTE: the service lives under ``ubo_app/services/000-system-metrics``, which is
not an importable package path, so the reducer is loaded via ``sys.path`` —
same pattern as ``test_sensors_reducer.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from redux import InitAction, InitializationActionError

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.services.system import SystemState


def _import_store_types_and_reducer() -> tuple[Any, Callable[..., Any]]:
    modules_before = set(sys.modules)

    from ubo_app.store.services import system as system_types

    service_dir = str(
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '000-system-metrics',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # type: ignore[import-not-found]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return system_types, reducer


types, reducer = _import_store_types_and_reducer()


def _state() -> SystemState:
    state = reducer(None, InitAction())
    assert isinstance(state, types.SystemState)
    return state


def test_none_state_without_init_raises() -> None:
    """A non-init action against a `None` state is an initialization error."""
    with pytest.raises(InitializationActionError):
        reducer(None, types.SystemStorageUpdateAction(
            disk_total_bytes=1,
            disk_used_bytes=1,
            disk_percent=1.0,
        ))


def test_init_produces_zeroed_metrics() -> None:
    """`InitAction` yields the empty slice, with no temperature reading."""
    state = _state()

    assert state.cpu_percent == 0.0
    assert state.ram_percent == 0.0
    assert state.cpu_temperature_celsius is None
    assert state.cpu_temperature_display_value is None
    assert state.cpu_temperature_display_unit is None
    assert state.boot_time == 0.0
    assert state.disk_total_bytes == 0
    assert state.network_upload_bps == 0.0


def test_metrics_update_populates_every_fast_field() -> None:
    """The one-second loop's action carries all of the fast-moving fields."""
    state = reducer(
        _state(),
        types.SystemMetricsUpdateAction(
            cpu_percent=34.5,
            ram_percent=61.25,
            cpu_temperature_celsius=52.5,
            cpu_temperature_display_value=126.5,
            cpu_temperature_display_unit='°F',
            load_average_1=0.31,
            load_average_5=0.28,
            load_average_15=0.25,
            boot_time=1700000000.0,
            network_upload_bps=12345.0,
            network_download_bps=1234567.0,
        ),
    )

    assert state.cpu_percent == 34.5
    assert state.ram_percent == 61.25
    assert state.cpu_temperature_celsius == 52.5
    assert state.cpu_temperature_display_value == 126.5
    assert state.cpu_temperature_display_unit == '°F'
    assert state.load_average_1 == 0.31
    assert state.load_average_5 == 0.28
    assert state.load_average_15 == 0.25
    assert state.boot_time == 1700000000.0
    assert state.network_upload_bps == 12345.0
    assert state.network_download_bps == 1234567.0


def test_metrics_update_keeps_a_missing_temperature_none() -> None:
    """Desktops expose no CPU thermal sensor; that must stay `None`, not 0."""
    state = reducer(
        _state(),
        types.SystemMetricsUpdateAction(
            cpu_percent=1.0,
            ram_percent=2.0,
        ),
    )

    assert state.cpu_temperature_celsius is None
    assert state.cpu_temperature_display_value is None
    assert state.cpu_temperature_display_unit is None


def test_storage_update_leaves_the_fast_fields_alone() -> None:
    """The slow disk loop must not clobber whatever the fast loop last wrote."""
    state = reducer(
        _state(),
        types.SystemMetricsUpdateAction(
            cpu_percent=34.5,
            ram_percent=61.25,
            cpu_temperature_celsius=52.5,
            boot_time=1700000000.0,
        ),
    )

    state = reducer(
        state,
        types.SystemStorageUpdateAction(
            disk_total_bytes=32 * 1024**3,
            disk_used_bytes=8 * 1024**3,
            disk_percent=25.0,
        ),
    )

    assert state.disk_total_bytes == 32 * 1024**3
    assert state.disk_used_bytes == 8 * 1024**3
    assert state.disk_percent == 25.0
    # Untouched by the storage arm.
    assert state.cpu_percent == 34.5
    assert state.cpu_temperature_celsius == 52.5
    assert state.boot_time == 1700000000.0


def test_unknown_action_returns_the_same_state() -> None:
    """An action the slice doesn't own passes through unchanged."""
    state = _state()

    assert reducer(state, types.SystemAction()) is state
