"""Server-side unit conversion. Clients must never do this themselves.

Pure functions only: no store access, so this is trivially unit-testable and
reusable from the localization reducer, the sensors menu, and system-metrics.
"""

from __future__ import annotations

from ubo_app.store.services.localization import UnitSystem

# Countries that report ambient temperature in Fahrenheit day to day.
FAHRENHEIT_COUNTRIES = frozenset({'US', 'LR', 'MM'})


def resolve_unit_system(
    unit_system: UnitSystem,
    country_code: str | None,
) -> UnitSystem:
    """Turn ``AUTO`` into a concrete ``METRIC``/``US`` using *country_code*.

    ``METRIC``/``US`` pass through unchanged — an explicit pick is sticky.
    ``AUTO`` with no country known yet falls back to ``METRIC``.
    """
    if unit_system != UnitSystem.AUTO:
        return unit_system
    if country_code and country_code.upper() in FAHRENHEIT_COUNTRIES:
        return UnitSystem.US
    return UnitSystem.METRIC


def convert_temperature_c(value: float, system: UnitSystem) -> tuple[float, str]:
    """Celsius in, (display_value, display_unit) out. *system* must be resolved."""
    if system == UnitSystem.US:
        return value * 9 / 5 + 32, '°F'
    return value, '°C'


def convert_speed_mps(value: float, system: UnitSystem) -> tuple[float, str]:
    """m/s in, (display_value, display_unit) out. Used for wind speed."""
    if system == UnitSystem.US:
        return value * 2.236936, 'mph'
    return value * 3.6, 'km/h'


def convert_distance(
    value: float,
    source_unit: str,
    system: UnitSystem,
) -> tuple[float, str]:
    """Convert a distance reading whose source unit is 'm' or 'cm'.

    Those are the two the sensor registry actually emits (bmp388 altitude in
    'm', vl53l1x proximity in 'cm'). Any other source unit passes through
    unconverted — safer to show the raw value than guess at an unknown unit.
    """
    meters = {'m': value, 'cm': value / 100}.get(source_unit)
    if meters is None:
        return value, source_unit
    if system == UnitSystem.US:
        if source_unit == 'cm':
            return meters * 39.3701, 'in'
        return meters * 3.28084, 'ft'
    return (meters, 'm') if source_unit == 'm' else (value, source_unit)


def convert_pressure_hpa(value: float, system: UnitSystem) -> tuple[float, str]:
    """HPa in, (display_value, display_unit) out.

    US customary meteorological pressure is conventionally inHg.
    """
    if system == UnitSystem.US:
        return value * 0.0295300, 'inHg'
    return value, 'hPa'
