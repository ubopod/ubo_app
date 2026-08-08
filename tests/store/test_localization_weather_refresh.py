"""Tests for the weather refresher's staleness gate.

The localization service re-fetches the forecast on a coarse ten-minute tick,
but the tick is not what decides: MET Norway's terms ask clients to honour the
`Expires` header rather than poll on a schedule of their own, so every path
that might issue a request first asks `is_stale`. That predicate is what these
tests pin down.

`setup.py` itself is not imported here — it boots the store at import time —
so the rule lives in `weather.py`, alongside the `Expires` parsing that
produces the `expires_at` it reads.
"""

from __future__ import annotations

from pathlib import Path

from tests.service_loader import load_service_modules
from ubo_app.store.services.localization import WeatherCondition

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '010-localization'
)

(weather,) = load_service_modules(SERVICE_DIR, 'weather')

NOW = 1_700_000_000.0


def _condition(expires_at: float) -> WeatherCondition:
    return WeatherCondition(
        symbol_code='partlycloudy_day',
        temperature_celsius=21.0,
        wind_speed_mps=3.0,
        fetched_at=NOW - 60,
        expires_at=expires_at,
    )


def test_absent_forecast_is_stale() -> None:
    """A cold cache always warrants a fetch."""
    assert weather.is_stale(None, now=NOW) is True


def test_expired_forecast_is_stale() -> None:
    """Past the `Expires` header, a re-request is allowed."""
    assert weather.is_stale(_condition(NOW - 1), now=NOW) is True


def test_forecast_expiring_exactly_now_is_stale() -> None:
    """The boundary counts as expired — the header is inclusive."""
    assert weather.is_stale(_condition(NOW), now=NOW) is True


def test_unexpired_forecast_is_not_stale() -> None:
    """Inside the window, re-requesting would violate MET Norway's terms."""
    assert weather.is_stale(_condition(NOW + 600), now=NOW) is False


def test_refresh_interval_is_coarser_than_a_minute() -> None:
    """The wake tick is a heartbeat, not a poll — weather moves slowly."""
    (constants,) = load_service_modules(SERVICE_DIR, 'constants')

    assert constants.WEATHER_REFRESH_CHECK_SECONDS >= 60
