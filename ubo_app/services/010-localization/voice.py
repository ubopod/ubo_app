"""Spoken answers for the time / date / weather voice shortcuts.

These are stage-1 shortcuts: an exact phrase match answers straight from device
state and the TTS engine, with no LLM round-trip. The formatters here are pure
so they can be tested without a store, a clock, or a network.

English-only for now; when the localization service grows a spoken-language
concept these become the seam to localize.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weather import describe_symbol

from ubo_app.store.core.bindable_actions import register_bindable_action
from ubo_app.store.services.localization import (
    LocalizationSpeakDateAction,
    LocalizationSpeakTimeAction,
    LocalizationSpeakWeatherAction,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ubo_app.store.services.localization import LocationInfo, WeatherCondition

SPEAK_TIME_KEY = 'localization:speak-time'
SPEAK_DATE_KEY = 'localization:speak-date'
SPEAK_WEATHER_KEY = 'localization:speak-weather'

UNKNOWN_LOCATION_TEXT = (
    "I don't know where this device is yet. Once it's online I'll work it out, "
    'or you can tell me where you are.'
)
WEATHER_UNAVAILABLE_TEXT = "I couldn't reach the weather service just now."

# The three countries that still speak Fahrenheit day to day.
_FAHRENHEIT_COUNTRIES = frozenset({'US', 'LR', 'MM'})


def _ordinal(day: int) -> str:
    # 11th/12th/13th are the exceptions the naive rule gets wrong.
    if 11 <= day % 100 <= 13:  # noqa: PLR2004
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    return f'{day}{suffix}'


def format_spoken_time(now: datetime) -> str:
    """Say the time the way a person would: "It's 3:05 PM."."""
    hour = now.hour % 12 or 12
    meridiem = 'AM' if now.hour < 12 else 'PM'  # noqa: PLR2004
    return f"It's {hour}:{now.minute:02d} {meridiem}."


def format_spoken_date(now: datetime) -> str:
    """Say the date: "It's Friday, July 11th."."""
    return (
        f"It's {now.strftime('%A')}, {now.strftime('%B')} {_ordinal(now.day)}."
    )


def uses_fahrenheit(location: LocationInfo | None) -> bool:
    """Whether *location*'s country reports temperature in Fahrenheit."""
    if location is None or not location.country_code:
        return False
    return location.country_code.upper() in _FAHRENHEIT_COUNTRIES


def format_spoken_weather(
    weather: WeatherCondition,
    location: LocationInfo | None,
) -> str:
    """Say the current conditions: "It's 21 degrees and partly cloudy in Berlin."."""
    if uses_fahrenheit(location):
        degrees = round(weather.temperature_celsius * 9 / 5 + 32)
    else:
        degrees = round(weather.temperature_celsius)

    description = describe_symbol(weather.symbol_code)
    where = f' in {location.city}' if location and location.city else ''
    return f"It's {degrees} degrees and {description}{where}."


def register_voice_bindable_actions() -> None:
    """Expose the three spoken answers as bindable voice-shortcut actions.

    The factories must be synchronous and return a single action, so they return
    a plain "speak" action; the reducer turns it into an event carrying a state
    snapshot, and the async handler in ``setup`` does the formatting (and, for
    weather, any refetch).
    """
    register_bindable_action(
        SPEAK_TIME_KEY,
        'Speak: Current Time',
        lambda _context: LocalizationSpeakTimeAction(),
        allow_reregister=True,
    )
    register_bindable_action(
        SPEAK_DATE_KEY,
        'Speak: Current Date',
        lambda _context: LocalizationSpeakDateAction(),
        allow_reregister=True,
    )
    register_bindable_action(
        SPEAK_WEATHER_KEY,
        'Speak: Weather',
        lambda _context: LocalizationSpeakWeatherAction(),
        allow_reregister=True,
    )
