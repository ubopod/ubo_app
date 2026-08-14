"""Pure tests for ``ubo_app.utils.units`` — no store, no service loading."""

from __future__ import annotations

import pytest

from ubo_app.store.services.localization import UnitSystem
from ubo_app.utils.units import (
    convert_distance,
    convert_pressure_hpa,
    convert_speed_mps,
    convert_temperature_c,
    resolve_unit_system,
)


def test_resolve_unit_system_auto_with_fahrenheit_country() -> None:
    """AUTO resolves to US for the three Fahrenheit-reporting countries."""
    assert resolve_unit_system(UnitSystem.AUTO, 'US') == UnitSystem.US
    assert resolve_unit_system(UnitSystem.AUTO, 'us') == UnitSystem.US
    assert resolve_unit_system(UnitSystem.AUTO, 'LR') == UnitSystem.US
    assert resolve_unit_system(UnitSystem.AUTO, 'MM') == UnitSystem.US


def test_resolve_unit_system_auto_with_metric_country() -> None:
    """AUTO resolves to Metric for everywhere else."""
    assert resolve_unit_system(UnitSystem.AUTO, 'DE') == UnitSystem.METRIC
    assert resolve_unit_system(UnitSystem.AUTO, 'PT') == UnitSystem.METRIC


def test_resolve_unit_system_auto_with_no_country_falls_back_to_metric() -> None:
    """No country known yet defaults to Metric, not a guess."""
    assert resolve_unit_system(UnitSystem.AUTO, None) == UnitSystem.METRIC
    assert resolve_unit_system(UnitSystem.AUTO, '') == UnitSystem.METRIC


def test_resolve_unit_system_explicit_pick_ignores_country() -> None:
    """An explicit pick is sticky — it never gets resolved against the country."""
    assert resolve_unit_system(UnitSystem.METRIC, 'US') == UnitSystem.METRIC
    assert resolve_unit_system(UnitSystem.US, 'DE') == UnitSystem.US


def test_convert_temperature_c() -> None:
    """Celsius passes through under Metric; converts to Fahrenheit under US."""
    assert convert_temperature_c(0.0, UnitSystem.METRIC) == (0.0, '°C')
    assert convert_temperature_c(0.0, UnitSystem.US) == (32.0, '°F')
    assert convert_temperature_c(100.0, UnitSystem.US) == (212.0, '°F')


def test_convert_speed_mps() -> None:
    """m/s converts to km/h under Metric, mph under US."""
    value, unit = convert_speed_mps(10.0, UnitSystem.METRIC)
    assert unit == 'km/h'
    assert value == pytest.approx(36.0)

    value, unit = convert_speed_mps(10.0, UnitSystem.US)
    assert unit == 'mph'
    assert value == pytest.approx(22.36936)


def test_convert_distance_meters_source() -> None:
    """A meter-sourced reading (e.g. altitude) converts to feet under US."""
    value, unit = convert_distance(2.0, 'm', UnitSystem.METRIC)
    assert (value, unit) == (2.0, 'm')

    value, unit = convert_distance(2.0, 'm', UnitSystem.US)
    assert unit == 'ft'
    assert value == pytest.approx(6.56168)


def test_convert_distance_centimeters_source() -> None:
    """A cm-sourced reading (e.g. proximity) converts independently of 'm'.

    The registry uses 'cm' for a different sensor than its 'm' altitude —
    each source unit must convert on its own, not via a fixed device_class
    assumption.
    """
    value, unit = convert_distance(30.0, 'cm', UnitSystem.METRIC)
    assert (value, unit) == (30.0, 'cm')

    value, unit = convert_distance(30.0, 'cm', UnitSystem.US)
    assert unit == 'in'
    assert value == pytest.approx(11.81103)


def test_convert_distance_unknown_source_unit_passes_through() -> None:
    """Safer to show the raw value than guess at an unrecognized unit."""
    assert convert_distance(5.0, 'furlong', UnitSystem.US) == (5.0, 'furlong')
    assert convert_distance(5.0, 'furlong', UnitSystem.METRIC) == (5.0, 'furlong')


def test_convert_pressure_hpa() -> None:
    """HPa passes through under Metric; converts to inHg under US."""
    assert convert_pressure_hpa(1013.25, UnitSystem.METRIC) == (1013.25, 'hPa')
    value, unit = convert_pressure_hpa(1013.25, UnitSystem.US)
    assert unit == 'inHg'
    assert value == pytest.approx(29.9213, rel=1e-3)
