"""Tests for IP geolocation, weather fetching, and the spoken answers.

The service modules are loaded by file path (the service directory is hyphenated
and therefore not importable), with the directory on ``sys.path`` so their
sibling ``from constants import ...`` / ``from weather import ...`` imports
resolve the same way they do at runtime.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import SimpleNamespace

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/010-localization'


def _load_module(monkeypatch: pytest.MonkeyPatch, name: str) -> Any:  # noqa: ANN401
    """Load a module from the hyphenated service directory."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    import ubo_app.store.services.localization as localization_module

    importlib.reload(localization_module)

    spec = importlib.util.spec_from_file_location(
        f'localization_service_{name}',
        SERVICE_PATH / f'{name}.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# aiohttp doubles (same shape as tests/store/test_update_manager_utils.py)
# --------------------------------------------------------------------------- #


class _Response:
    def __init__(
        self,
        payload: object,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status = status
        self.headers = dict(headers or {})
        self.requested_url: str | None = None
        self.requested_headers: dict[str, str] = {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self, *, content_type: str | None = None) -> object:  # noqa: ARG002
        return self._payload

    def raise_for_status(self) -> None:
        if self.status >= 400:
            msg = f'HTTP {self.status}'
            raise OSError(msg)


class _Session:
    def __init__(self, response: _Response) -> None:
        self._response = response

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        raise_for_status: bool = False,  # noqa: ARG002
    ) -> _Response:
        self._response.requested_url = url
        self._response.requested_headers = dict(headers or {})
        return self._response


class _FailingSession:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def get(self, *_args: object, **_kwargs: object) -> _Response:
        msg = 'network is down'
        raise OSError(msg)


def _patch_http(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,  # noqa: ANN401
    response: _Response | None,
) -> None:
    session = _Session(response) if response is not None else _FailingSession()
    monkeypatch.setattr(module.aiohttp, 'ClientSession', lambda **_kwargs: session)


GEOJS_PAYLOAD = {
    'city': 'Berlin',
    'country': 'Germany',
    'country_code': 'DE',
    'latitude': '52.5244',
    'longitude': '13.4105',
    'timezone': 'Europe/Berlin',
    'ip': '198.51.100.7',
}


# --------------------------------------------------------------------------- #
# Geolocation
# --------------------------------------------------------------------------- #


async def test_fetch_geolocation_parses_a_geojs_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed GeoJS response becomes a usable location."""
    geolocation = _load_module(monkeypatch, 'geolocation')
    _patch_http(monkeypatch, geolocation, _Response(GEOJS_PAYLOAD))

    result = await geolocation.fetch_geolocation()

    assert result is not None
    assert result.public_ip == '198.51.100.7'
    assert result.location.city == 'Berlin'
    assert result.location.country_code == 'DE'
    assert result.location.timezone == 'Europe/Berlin'
    assert result.location.latitude == pytest.approx(52.5244)


async def test_fetch_geolocation_returns_none_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The device is often offline at boot — that must not raise."""
    geolocation = _load_module(monkeypatch, 'geolocation')
    _patch_http(monkeypatch, geolocation, None)

    assert await geolocation.fetch_geolocation() is None


async def test_fetch_geolocation_returns_none_without_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coordinates are the one field we cannot do without."""
    geolocation = _load_module(monkeypatch, 'geolocation')
    _patch_http(monkeypatch, geolocation, _Response({'city': 'Nowhere'}))

    assert await geolocation.fetch_geolocation() is None


def test_parse_geolocation_tolerates_missing_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coordinates alone are enough; the rest degrade to ``None``."""
    geolocation = _load_module(monkeypatch, 'geolocation')

    result = geolocation.parse_geolocation({'latitude': 1.5, 'longitude': -2.5})

    assert result is not None
    assert result.location.city is None
    assert result.public_ip is None


def test_should_apply_geolocation_skips_a_manual_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Automatic detection must never overwrite what the user set by hand."""
    geolocation = _load_module(monkeypatch, 'geolocation')
    from ubo_app.store.services.localization import LocationSource

    result = geolocation.parse_geolocation(GEOJS_PAYLOAD)

    assert not geolocation.should_apply_geolocation(
        result,
        current_public_ip=None,
        location_source=LocationSource.MANUAL,
        has_location=True,
    )


def test_should_apply_geolocation_skips_an_unchanged_public_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same public IP means same location — the lookup is its own change check."""
    geolocation = _load_module(monkeypatch, 'geolocation')
    from ubo_app.store.services.localization import LocationSource

    result = geolocation.parse_geolocation(GEOJS_PAYLOAD)

    assert not geolocation.should_apply_geolocation(
        result,
        current_public_ip='198.51.100.7',
        location_source=LocationSource.IP,
        has_location=True,
    )
    # A different IP, or no location yet, does warrant an update.
    assert geolocation.should_apply_geolocation(
        result,
        current_public_ip='203.0.113.9',
        location_source=LocationSource.IP,
        has_location=True,
    )
    assert geolocation.should_apply_geolocation(
        result,
        current_public_ip='198.51.100.7',
        location_source=LocationSource.IP,
        has_location=False,
    )


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #

FORECAST_PAYLOAD = {
    'properties': {
        'timeseries': [
            {
                'data': {
                    'instant': {
                        'details': {
                            'air_temperature': 21.3,
                            'wind_speed': 3.2,
                        },
                    },
                    'next_1_hours': {
                        'summary': {'symbol_code': 'partlycloudy_day'},
                    },
                },
            },
        ],
    },
}


async def test_fetch_weather_parses_a_met_no_forecast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first timeseries entry is the current conditions."""
    weather = _load_module(monkeypatch, 'weather')
    from ubo_app.store.services.localization import LocationInfo

    response = _Response(
        FORECAST_PAYLOAD,
        headers={'Expires': 'Fri, 11 Jul 2036 12:00:00 GMT'},
    )
    _patch_http(monkeypatch, weather, response)

    condition = await weather.fetch_weather(
        LocationInfo(latitude=52.524399, longitude=13.410500),
    )

    assert condition is not None
    assert condition.symbol_code == 'partlycloudy_day'
    assert condition.temperature_celsius == pytest.approx(21.3)
    assert condition.wind_speed_mps == pytest.approx(3.2)
    # Honour the Expires header rather than inventing a TTL.
    assert condition.expires_at == pytest.approx(
        datetime(2036, 7, 11, 12, 0, tzinfo=UTC).timestamp(),
    )


async def test_fetch_weather_truncates_coordinates_and_identifies_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MET Norway's terms require both — coordinates ≤ 4 decimals and a real UA."""
    weather = _load_module(monkeypatch, 'weather')
    from ubo_app.store.services.localization import LocationInfo

    response = _Response(FORECAST_PAYLOAD)
    _patch_http(monkeypatch, weather, response)

    await weather.fetch_weather(
        LocationInfo(latitude=52.5243987654, longitude=-13.4105123456),
    )

    assert response.requested_url is not None
    assert 'lat=52.5244' in response.requested_url
    assert 'lon=-13.4105' in response.requested_url
    user_agent = response.requested_headers.get('User-Agent', '')
    assert 'ubo-app' in user_agent
    assert 'getubo.com' in user_agent


async def test_fetch_weather_returns_none_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A weather outage degrades to "I couldn't reach it", never a crash."""
    weather = _load_module(monkeypatch, 'weather')
    from ubo_app.store.services.localization import LocationInfo

    _patch_http(monkeypatch, weather, None)

    assert (
        await weather.fetch_weather(LocationInfo(latitude=1.0, longitude=2.0))
        is None
    )


def test_describe_symbol_strips_suffixes_and_handles_unknowns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol codes become phrases a TTS engine can say out loud."""
    weather = _load_module(monkeypatch, 'weather')

    assert weather.describe_symbol('partlycloudy_day') == 'partly cloudy'
    assert weather.describe_symbol('partlycloudy_night') == 'partly cloudy'
    assert weather.describe_symbol('clearsky_polartwilight') == 'clear'
    assert weather.describe_symbol('lightrainshowers_day') == 'lightly showery'
    # An unknown code still says something rather than reading the raw token.
    assert weather.describe_symbol('meteor_shower_day') == 'meteor shower'


# --------------------------------------------------------------------------- #
# Spoken answers
# --------------------------------------------------------------------------- #


def _voice(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    _load_module(monkeypatch, 'weather')
    return _load_module(monkeypatch, 'voice')


def test_format_spoken_time_uses_a_twelve_hour_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Midnight and noon are the two the naive modulo gets wrong."""
    voice = _voice(monkeypatch)

    assert (
        voice.format_spoken_time(datetime(2026, 7, 11, 15, 5, tzinfo=UTC))
        == "It's 3:05 PM."
    )
    assert (
        voice.format_spoken_time(datetime(2026, 7, 11, 0, 7, tzinfo=UTC))
        == "It's 12:07 AM."
    )
    assert (
        voice.format_spoken_time(datetime(2026, 7, 11, 12, 0, tzinfo=UTC))
        == "It's 12:00 PM."
    )


def test_format_spoken_date_reads_an_ordinal_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"July 11th", not "July 11" — and the teens are the trap."""
    voice = _voice(monkeypatch)

    assert (
        voice.format_spoken_date(datetime(2026, 7, 11, tzinfo=UTC))
        == "It's Saturday, July 11th."
    )
    assert (
        voice.format_spoken_date(datetime(2026, 7, 1, tzinfo=UTC))
        == "It's Wednesday, July 1st."
    )
    assert (
        voice.format_spoken_date(datetime(2026, 7, 22, tzinfo=UTC))
        == "It's Wednesday, July 22nd."
    )
    assert (
        voice.format_spoken_date(datetime(2026, 7, 23, tzinfo=UTC))
        == "It's Thursday, July 23rd."
    )


def test_format_spoken_weather_reports_celsius_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Most of the world hears Celsius."""
    voice = _voice(monkeypatch)
    from ubo_app.store.services.localization import LocationInfo, WeatherCondition

    text = voice.format_spoken_weather(
        WeatherCondition(symbol_code='partlycloudy_day', temperature_celsius=21.4),
        LocationInfo(
            latitude=52.52,
            longitude=13.4,
            city='Berlin',
            country_code='DE',
        ),
    )

    assert text == "It's 21 degrees and partly cloudy in Berlin."


def test_format_spoken_weather_reports_fahrenheit_in_the_us(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A device in the US should not be told it's 21 degrees outside."""
    voice = _voice(monkeypatch)
    from ubo_app.store.services.localization import LocationInfo, WeatherCondition

    text = voice.format_spoken_weather(
        WeatherCondition(symbol_code='clearsky_day', temperature_celsius=21.0),
        LocationInfo(
            latitude=37.77,
            longitude=-122.42,
            city='San Francisco',
            country_code='US',
        ),
    )

    assert text == "It's 70 degrees and clear in San Francisco."


def test_format_spoken_weather_without_a_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No city name just means no trailing "in X"."""
    voice = _voice(monkeypatch)
    from ubo_app.store.services.localization import WeatherCondition

    text = voice.format_spoken_weather(
        WeatherCondition(symbol_code='rain', temperature_celsius=11.0),
        None,
    )

    assert text == "It's 11 degrees and raining."
