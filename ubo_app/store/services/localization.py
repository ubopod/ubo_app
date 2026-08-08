# ruff: noqa: D100, D101
from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import cast

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class LanguageCode(StrEnum):
    """Top-level language families supported by the device.

    Only families with at least one curated Piper voice appear here.
    Sub-locales (e.g. ``en_US`` vs ``en_GB``) are represented at the
    voice level inside ``piper_catalog`` rather than as separate enum
    members — the localization layer cares about language, not accent.
    """

    EN = 'en'
    DE = 'de'
    ES = 'es'
    FR = 'fr'
    IT = 'it'
    PT = 'pt'
    NL = 'nl'
    ZH = 'zh'


_LANGUAGE_LABELS: dict[LanguageCode, str] = {
    LanguageCode.EN: 'English',
    LanguageCode.DE: 'German',
    LanguageCode.ES: 'Spanish',
    LanguageCode.FR: 'French',
    LanguageCode.IT: 'Italian',
    LanguageCode.PT: 'Portuguese',
    LanguageCode.NL: 'Dutch',
    LanguageCode.ZH: 'Chinese',
}


def language_label(code: LanguageCode) -> str:
    """Return the human-readable label for *code*."""
    return _LANGUAGE_LABELS.get(code, code.value)


class LocationSource(StrEnum):
    """Where the currently stored location came from.

    ``IP`` locations are refreshed automatically whenever connectivity or the
    public IP changes. ``MANUAL`` locations are never overwritten by the
    automatic detector — only an explicit reset returns the device to ``IP``.
    """

    IP = 'ip'
    MANUAL = 'manual'


class LocationInfo(Immutable):
    """Where the device is, as far as the device knows."""

    latitude: float
    longitude: float
    city: str | None = None
    country: str | None = None
    country_code: str | None = None
    timezone: str | None = None


class WeatherCondition(Immutable):
    """A snapshot of the current weather at the device's location.

    ``fetched_at`` / ``expires_at`` are epoch seconds. Freshness is decided by
    the async handlers that consume this — reducers never read the clock.
    """

    symbol_code: str
    temperature_celsius: float
    wind_speed_mps: float | None = None
    fetched_at: float = 0
    expires_at: float = 0


class LocalizationAction(BaseAction): ...


class LocalizationEvent(BaseEvent): ...


class LocalizationSetLanguageAction(LocalizationAction):
    language: LanguageCode


class LocalizationSetLocationAction(LocalizationAction):
    location: LocationInfo
    source: LocationSource
    public_ip: str | None = None


class LocalizationResetLocationAction(LocalizationAction): ...


class LocalizationUpdateWeatherAction(LocalizationAction):
    weather: WeatherCondition


class LocalizationRefreshWeatherAction(LocalizationAction): ...


class LocalizationUpdateClockAction(LocalizationAction):
    """Publish the wall clock at the device's location.

    Dispatched only when one of the two strings actually changes, so the clock
    costs the store one update a minute rather than one a tick.
    """

    clock: str  # Format: "HH:MM"
    date: str  # Format: "YYYY-MM-DD"


class LocalizationSpeakTimeAction(LocalizationAction): ...


class LocalizationSpeakDateAction(LocalizationAction): ...


class LocalizationSpeakWeatherAction(LocalizationAction): ...


class LocalizationLanguageChangedEvent(LocalizationEvent):
    language: LanguageCode


class LocalizationLocationChangedEvent(LocalizationEvent):
    location: LocationInfo
    source: LocationSource


class LocalizationLocationResetEvent(LocalizationEvent): ...


class LocalizationWeatherRefreshRequestedEvent(LocalizationEvent):
    location: LocationInfo


class LocalizationSpeakTimeEvent(LocalizationEvent):
    timezone: str | None = None


class LocalizationSpeakDateEvent(LocalizationEvent):
    timezone: str | None = None


class LocalizationSpeakWeatherEvent(LocalizationEvent):
    weather: WeatherCondition | None = None
    location: LocationInfo | None = None


def _load_language(value: object) -> LanguageCode:
    if isinstance(value, LanguageCode):
        return value
    if isinstance(value, str):
        try:
            return LanguageCode(value)
        except ValueError:
            return LanguageCode.EN
    return LanguageCode.EN


def _load_location(value: object) -> LocationInfo | None:
    """Rebuild a ``LocationInfo`` from its persisted form, tolerating garbage."""
    if isinstance(value, LocationInfo):
        return value
    if not isinstance(value, dict):
        return None
    try:
        latitude = float(cast('float', value['latitude']))
        longitude = float(cast('float', value['longitude']))
    except (KeyError, TypeError, ValueError):
        return None

    def _optional_str(key: str) -> str | None:
        candidate = value.get(key)
        return candidate if isinstance(candidate, str) and candidate else None

    return LocationInfo(
        latitude=latitude,
        longitude=longitude,
        city=_optional_str('city'),
        country=_optional_str('country'),
        country_code=_optional_str('country_code'),
        timezone=_optional_str('timezone'),
    )


def _load_location_source(value: object) -> LocationSource:
    if isinstance(value, LocationSource):
        return value
    if isinstance(value, str):
        try:
            return LocationSource(value)
        except ValueError:
            return LocationSource.IP
    return LocationSource.IP


def _load_public_ip(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


class LocalizationState(Immutable):
    language: LanguageCode = field(
        default=read_from_persistent_store(
            key='localization:language',
            default=LanguageCode.EN,
            mapper=_load_language,
        ),
    )
    location: LocationInfo | None = field(
        default_factory=lambda: read_from_persistent_store(
            key='localization:location',
            default=None,
            mapper=_load_location,
        ),
    )
    location_source: LocationSource = field(
        default_factory=lambda: read_from_persistent_store(
            key='localization:location_source',
            default=LocationSource.IP,
            mapper=_load_location_source,
        ),
    )
    public_ip: str | None = field(
        default_factory=lambda: read_from_persistent_store(
            key='localization:public_ip',
            default=None,
            mapper=_load_public_ip,
        ),
    )
    # Deliberately not persisted: a weather snapshot from the last boot is
    # always stale, and re-fetching costs one request.
    weather: WeatherCondition | None = None
    # The wall clock *at the device's location*, which is not necessarily the
    # host's timezone — nothing sets the OS zone from the detected location.
    # This service owns the location, so it owns the time there too; the status
    # bar and every client read these rather than computing their own.
    clock: str = ''
    date: str = ''
