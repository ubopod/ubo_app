"""Implement `init_service` for the localization service.

Provides Settings → Localization: the Language picker, and Location — where the
device thinks it is. The location (city, country, coordinates, IANA timezone) is
detected automatically from the public IP, persisted (this is a stationary
device), and can be corrected by hand or reset back to automatic.

That location is what powers the "what time is it" / "what day is it" /
"what's the weather" voice shortcuts, which answer straight from device state
and the TTS engine without involving the assistant's LLM.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from constants import GEO_BACKOFF_SCHEDULE, GEO_DEBOUNCE_SECONDS
from geolocation import fetch_geolocation, should_apply_geolocation
from location_menu import (
    LOCATION_MENU_ID,
    OPEN_LOCATION_ACTION_ID,
    register_location_actions,
)
from voice import (
    UNKNOWN_LOCATION_TEXT,
    WEATHER_UNAVAILABLE_TEXT,
    format_spoken_date,
    format_spoken_time,
    format_spoken_weather,
    register_voice_bindable_actions,
)
from weather import fetch_weather

from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import (
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.localization import (
    LanguageCode,
    LocalizationLocationResetEvent,
    LocalizationSetLanguageAction,
    LocalizationSetLocationAction,
    LocalizationSpeakDateEvent,
    LocalizationSpeakTimeEvent,
    LocalizationSpeakWeatherEvent,
    LocalizationUpdateWeatherAction,
    LocalizationWeatherRefreshRequestedEvent,
    LocationSource,
    language_label,
)
from ubo_app.store.services.speech_synthesis import (
    ReadableInformation,
    SpeechSynthesisReadTextAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.menu_items import build_selection_menu
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.services.localization import LocationInfo, WeatherCondition
    from ubo_app.utils.types import Subscriptions


LANGUAGE_MENU_ID = 'localization:language'
OPEN_LANGUAGE_ACTION_ID = 'localization:open_language_picker'


def _register_language_actions() -> None:
    for code in LanguageCode:
        action_id = f'localization:set_language:{code.value}'

        def _make_handler(target: LanguageCode) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(LocalizationSetLanguageAction(language=target))

            return _handler

        register_action(action_id, _make_handler(code), allow_reregister=True)


@store.autorun(lambda state: state.localization.language)
def _build_language_menu(selected_language: LanguageCode) -> None:
    """Rebuild the language picker whenever the selection changes."""
    _register_language_actions()

    options = tuple(
        (
            code.value,
            language_label(code),
            f'localization:set_language:{code.value}',
        )
        for code in LanguageCode
    )

    build_selection_menu(
        options=options,
        selected_key=selected_language.value,
        menu_id=LANGUAGE_MENU_ID,
        title='Language',
        heading='System Language',
        sub_heading=(
            'Pick the language used for assistant voices and other '
            'localised features.'
        ),
    )


def _open_language_picker() -> None:
    store.dispatch(StackPushMenuAction(menu_key=LANGUAGE_MENU_ID))


def _open_location_menu() -> None:
    store.dispatch(StackPushMenuAction(menu_key=LOCATION_MENU_ID))


# --------------------------------------------------------------------------- #
# Automatic location detection
# --------------------------------------------------------------------------- #

# Bumped by the connectivity autorun; the detector uses it to tell "the link
# settled" from "the link flapped again while we were waiting".
_generation = 0
_detect_requested = asyncio.Event()


@store.autorun(
    lambda state: (
        # 010 loads before 030-ip, so the slice may not exist yet.
        getattr(getattr(state, 'ip', None), 'is_connected', None),
        tuple(
            sorted(
                address
                for interface in getattr(
                    getattr(state, 'ip', None),
                    'interfaces',
                    (),
                )
                for address in interface.ip_addresses
            ),
        ),
    ),
)
def _watch_connectivity(data: tuple[bool | None, tuple[str, ...]]) -> None:
    """Ask for a lookup whenever the device (re)gains a network."""
    global _generation  # noqa: PLW0603

    is_connected, _addresses = data
    if not is_connected:
        return

    # Either a fresh connection or a changed set of local IPs (new network,
    # ethernet plugged in) — both usually mean a new public IP.
    _generation += 1
    _detect_requested.set()


@store.with_state(
    lambda state: (
        state.localization.location is not None,
        state.localization.location_source,
        state.localization.public_ip,
    ),
)
def _location_snapshot(
    data: tuple[bool, LocationSource, str | None],
) -> tuple[bool, LocationSource, str | None]:
    return data


async def _detect_location() -> bool:
    """Run one lookup and apply it if it tells us something new."""
    has_location, location_source, public_ip = _location_snapshot()

    if location_source is LocationSource.MANUAL:
        logger.debug('Localization: location is manual, skipping IP detection')
        return True

    result = await fetch_geolocation()
    if result is None:
        return False

    if not should_apply_geolocation(
        result,
        current_public_ip=public_ip,
        location_source=location_source,
        has_location=has_location,
    ):
        logger.debug('Localization: public IP unchanged, keeping known location')
        return True

    logger.info(
        'Localization: location detected from IP',
        extra={
            'city': result.location.city,
            'country': result.location.country,
            'timezone': result.location.timezone,
        },
    )
    store.dispatch(
        LocalizationSetLocationAction(
            location=result.location,
            source=LocationSource.IP,
            public_ip=result.public_ip,
        ),
    )
    return True


async def _monitor_location(end_event: asyncio.Event) -> None:
    """Detect the location whenever connectivity settles, with backoff on failure."""
    while not end_event.is_set():
        await _detect_requested.wait()
        _detect_requested.clear()

        # Let the link settle: connectivity flaps during association, and a
        # captive portal briefly looks "connected" while hijacking traffic.
        generation = _generation
        await asyncio.sleep(GEO_DEBOUNCE_SECONDS)
        if _generation != generation:
            # Something changed again while we waited — restart the wait rather
            # than spend a lookup on a link that is still moving.
            _detect_requested.set()
            continue

        for backoff in (*GEO_BACKOFF_SCHEDULE, None):
            if end_event.is_set() or await _detect_location():
                break
            if backoff is None:
                logger.warning('Localization: giving up on IP geolocation for now')
                report_service_error()
                break
            await asyncio.sleep(backoff)
            if _generation != generation:
                # A newer request supersedes this retry chain.
                break


def _request_detection(_event: LocalizationLocationResetEvent) -> None:
    """Re-detect immediately: a reset means "forget what I told you"."""
    global _generation  # noqa: PLW0603

    _generation += 1
    _detect_requested.set()


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #

_weather_lock = asyncio.Lock()


async def _refresh_weather(location: LocationInfo) -> WeatherCondition | None:
    """Fetch and store the current conditions. Single-flight."""
    async with _weather_lock:
        condition = await fetch_weather(location)
        if condition is None:
            return None
        store.dispatch(LocalizationUpdateWeatherAction(weather=condition))
        return condition


def _handle_weather_refresh_requested(
    event: LocalizationWeatherRefreshRequestedEvent,
) -> None:
    create_task(_refresh_weather(event.location))


# --------------------------------------------------------------------------- #
# Spoken answers (stage-1 voice shortcuts)
# --------------------------------------------------------------------------- #


def _speak(text: str) -> None:
    store.dispatch(
        SpeechSynthesisReadTextAction(
            information=ReadableInformation(text=text),
        ),
    )


def _now(timezone: str | None) -> datetime:
    """Return the time at the device's location, or the system clock's."""
    if timezone:
        try:
            return datetime.now(ZoneInfo(timezone))
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                'Localization: unknown timezone, falling back to system clock',
                extra={'timezone': timezone},
            )
    return datetime.now().astimezone()


def _handle_speak_time(event: LocalizationSpeakTimeEvent) -> None:
    _speak(format_spoken_time(_now(event.timezone)))


def _handle_speak_date(event: LocalizationSpeakDateEvent) -> None:
    _speak(format_spoken_date(_now(event.timezone)))


async def _speak_weather(event: LocalizationSpeakWeatherEvent) -> None:
    if event.location is None:
        _speak(UNKNOWN_LOCATION_TEXT)
        return

    weather = event.weather
    if weather is None or weather.expires_at <= time.time():
        # Cache is cold or stale — someone is waiting on an answer, so fetch
        # now rather than report yesterday's sky.
        weather = await _refresh_weather(event.location)
        if weather is None:
            _speak(WEATHER_UNAVAILABLE_TEXT)
            return

    _speak(format_spoken_weather(weather, event.location))


def _handle_speak_weather(event: LocalizationSpeakWeatherEvent) -> None:
    create_task(_speak_weather(event))


def init_service() -> Subscriptions:
    """Initialize the localization service."""
    register_persistent_store(
        'localization:language',
        lambda state: state.localization.language,
    )
    register_persistent_store(
        'localization:location',
        lambda state: state.localization.location,
    )
    register_persistent_store(
        'localization:location_source',
        lambda state: state.localization.location_source,
    )
    register_persistent_store(
        'localization:public_ip',
        lambda state: state.localization.public_ip,
    )

    register_action(
        OPEN_LANGUAGE_ACTION_ID,
        _open_language_picker,
        allow_reregister=True,
    )
    register_action(
        OPEN_LOCATION_ACTION_ID,
        _open_location_menu,
        allow_reregister=True,
    )
    register_location_actions()
    register_voice_bindable_actions()

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.LOCALIZATION,
            priority=0,
            label='Language',
            icon='󰗊',
            action_id=OPEN_LANGUAGE_ACTION_ID,
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.LOCALIZATION,
            priority=1,
            label='Location',
            icon='󰍎',
            action_id=OPEN_LOCATION_ACTION_ID,
        ),
    )

    end_event = asyncio.Event()
    create_task(_monitor_location(end_event))

    logger.info('Localization service initialized')

    return [
        end_event.set,
        store.subscribe_event(LocalizationLocationResetEvent, _request_detection),
        store.subscribe_event(
            LocalizationWeatherRefreshRequestedEvent,
            _handle_weather_refresh_requested,
        ),
        store.subscribe_event(LocalizationSpeakTimeEvent, _handle_speak_time),
        store.subscribe_event(LocalizationSpeakDateEvent, _handle_speak_date),
        store.subscribe_event(LocalizationSpeakWeatherEvent, _handle_speak_weather),
    ]
