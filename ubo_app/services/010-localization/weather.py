"""Fetch current weather conditions from MET Norway (api.met.no).

No API key, global coverage, and commercial use is permitted — but the terms
require an identifying User-Agent, coordinates truncated to four decimals, and
that clients honour the ``Expires`` header instead of re-polling. All three are
implemented here. Data is licensed CC BY 4.0 (MET Norway / Yr).
"""

from __future__ import annotations

import time
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import aiohttp
from constants import (
    HTTP_TIMEOUT_SECONDS,
    MET_NO_URL,
    USER_AGENT,
    WEATHER_FALLBACK_TTL_SECONDS,
)

from ubo_app.logger import logger
from ubo_app.store.services.localization import WeatherCondition

if TYPE_CHECKING:
    from ubo_app.store.services.localization import LocationInfo

HTTP_NOT_MODIFIED = 304

# MET Norway symbol codes carry a `_day` / `_night` / `_polartwilight` suffix,
# which we strip before lookup — the spoken phrase is the same either way.
SYMBOL_PHRASES: dict[str, str] = {
    'clearsky': 'clear',
    'fair': 'fair',
    'partlycloudy': 'partly cloudy',
    'cloudy': 'cloudy',
    'fog': 'foggy',
    'rain': 'raining',
    'lightrain': 'lightly raining',
    'heavyrain': 'raining heavily',
    'rainshowers': 'showery',
    'lightrainshowers': 'lightly showery',
    'heavyrainshowers': 'heavily showery',
    'drizzle': 'drizzling',
    'sleet': 'sleeting',
    'lightsleet': 'lightly sleeting',
    'heavysleet': 'sleeting heavily',
    'sleetshowers': 'sleet showers',
    'lightsleetshowers': 'light sleet showers',
    'heavysleetshowers': 'heavy sleet showers',
    'snow': 'snowing',
    'lightsnow': 'lightly snowing',
    'heavysnow': 'snowing heavily',
    'snowshowers': 'snow showers',
    'lightsnowshowers': 'light snow showers',
    'heavysnowshowers': 'heavy snow showers',
    'rainandthunder': 'raining with thunder',
    'rainshowersandthunder': 'showers with thunder',
    'thunderstorm': 'thundery',
    'heavyrainandthunder': 'raining heavily with thunder',
    'snowandthunder': 'snowing with thunder',
    'sleetandthunder': 'sleeting with thunder',
}

_SUFFIXES = ('_day', '_night', '_polartwilight')

# Cache validators for conditional requests, keyed by request URL.
_validators: dict[str, dict[str, str]] = {}
_last_condition: dict[str, WeatherCondition] = {}


def describe_symbol(symbol_code: str) -> str:
    """Turn a MET Norway symbol code into something a TTS engine can say."""
    base = symbol_code
    for suffix in _SUFFIXES:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if base in SYMBOL_PHRASES:
        return SYMBOL_PHRASES[base]
    # Unknown codes still say *something* sensible rather than reading the
    # raw token aloud.
    return base.replace('_', ' ').replace('-', ' ') or 'unknown'


def is_stale(condition: WeatherCondition | None, *, now: float) -> bool:
    """Return whether *condition* should be re-fetched.

    MET Norway's terms ask clients to honour the `Expires` header rather than
    poll on a schedule of their own, so this — not the refresher's wake
    interval — is what decides whether a request goes out.
    """
    return condition is None or condition.expires_at <= now


def _expires_at(header: str | None) -> float:
    if header:
        try:
            return parsedate_to_datetime(header).timestamp()
        except (TypeError, ValueError):
            logger.debug(
                'Localization: unparsable Expires header',
                extra={'header': header},
            )
    return time.time() + WEATHER_FALLBACK_TTL_SECONDS


def parse_forecast(payload: object, *, expires_at: float) -> WeatherCondition | None:
    """Read the current conditions out of a locationforecast payload."""
    if not isinstance(payload, dict):
        return None
    try:
        entry = payload['properties']['timeseries'][0]
        details = entry['data']['instant']['details']
        temperature = float(details['air_temperature'])
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    data = entry.get('data', {})
    summary = data.get('next_1_hours') or data.get('next_6_hours') or {}
    symbol_code = summary.get('summary', {}).get('symbol_code')
    if not isinstance(symbol_code, str) or not symbol_code:
        symbol_code = 'unknown'

    wind_speed = details.get('wind_speed')
    try:
        wind_speed_mps = float(wind_speed) if wind_speed is not None else None
    except (TypeError, ValueError):
        wind_speed_mps = None

    return WeatherCondition(
        symbol_code=symbol_code,
        temperature_celsius=temperature,
        wind_speed_mps=wind_speed_mps,
        fetched_at=time.time(),
        expires_at=expires_at,
    )


async def fetch_weather(location: LocationInfo) -> WeatherCondition | None:
    """Fetch the current conditions at *location*. ``None`` on any failure."""
    # MET Norway rejects coordinates with more precision than this.
    url = (
        f'{MET_NO_URL}?lat={location.latitude:.4f}&lon={location.longitude:.4f}'
    )
    headers = {'User-Agent': USER_AGENT, **_validators.get(url, {})}

    try:
        async with (
            aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS),
            ) as session,
            session.get(url, headers=headers) as response,
        ):
            expires_at = _expires_at(response.headers.get('Expires'))

            if response.status == HTTP_NOT_MODIFIED:
                cached = _last_condition.get(url)
                if cached is not None:
                    # Same forecast, new validity window.
                    refreshed = WeatherCondition(
                        symbol_code=cached.symbol_code,
                        temperature_celsius=cached.temperature_celsius,
                        wind_speed_mps=cached.wind_speed_mps,
                        fetched_at=time.time(),
                        expires_at=expires_at,
                    )
                    _last_condition[url] = refreshed
                    return refreshed
                return None

            response.raise_for_status()
            payload = await response.json(content_type=None)
            validators = {
                header: response.headers[header]
                for header in ('Last-Modified',)
                if header in response.headers
            }
    except Exception:
        logger.exception('Localization: weather fetch failed')
        return None

    condition = parse_forecast(payload, expires_at=expires_at)
    if condition is None:
        logger.warning('Localization: unusable weather response')
        return None

    if 'Last-Modified' in validators:
        _validators[url] = {'If-Modified-Since': validators['Last-Modified']}
    _last_condition[url] = condition
    return condition
