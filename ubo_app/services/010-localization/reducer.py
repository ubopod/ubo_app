# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.services.localization import (
    LocalizationAction,
    LocalizationEvent,
    LocalizationLanguageChangedEvent,
    LocalizationLocationChangedEvent,
    LocalizationLocationResetEvent,
    LocalizationRefreshWeatherAction,
    LocalizationResetLocationAction,
    LocalizationSetLanguageAction,
    LocalizationSetLocationAction,
    LocalizationSetUnitSystemAction,
    LocalizationSpeakDateAction,
    LocalizationSpeakDateEvent,
    LocalizationSpeakTimeAction,
    LocalizationSpeakTimeEvent,
    LocalizationSpeakWeatherAction,
    LocalizationSpeakWeatherEvent,
    LocalizationState,
    LocalizationUnitSystemChangedEvent,
    LocalizationUpdateClockAction,
    LocalizationUpdateWeatherAction,
    LocalizationWeatherRefreshRequestedEvent,
    LocationSource,
    UnitSystem,
    WeatherCondition,
)
from ubo_app.utils.units import (
    convert_speed_mps,
    convert_temperature_c,
    resolve_unit_system,
)


def _recompute_weather_display(
    weather: WeatherCondition | None,
    unit_system: UnitSystem,
    country_code: str | None,
) -> WeatherCondition | None:
    """Fill in `WeatherCondition`'s display fields for the current settings.

    Single source of truth for "resolve AUTO, then convert" — every trigger
    that could invalidate the display fields (a fresh fetch, a unit-system
    change, a location/country change) goes through this, so they can never
    drift out of sync.
    """
    if weather is None:
        return None
    resolved = resolve_unit_system(unit_system, country_code)
    temperature_display_value, temperature_display_unit = convert_temperature_c(
        weather.temperature_celsius,
        resolved,
    )
    if weather.wind_speed_mps is None:
        wind_speed_display_value, wind_speed_display_unit = None, None
    else:
        wind_speed_display_value, wind_speed_display_unit = convert_speed_mps(
            weather.wind_speed_mps,
            resolved,
        )
    return replace(
        weather,
        temperature_display_value=temperature_display_value,
        temperature_display_unit=temperature_display_unit,
        wind_speed_display_value=wind_speed_display_value,
        wind_speed_display_unit=wind_speed_display_unit,
    )


def reducer(
    state: LocalizationState | None,
    action: LocalizationAction,
) -> (
    LocalizationState
    | CompleteReducerResult[
        LocalizationState,
        LocalizationAction,
        LocalizationEvent,
    ]
):
    if state is None:
        if isinstance(action, InitAction):
            return LocalizationState()
        raise InitializationActionError(action)

    match action:
        case LocalizationSetLanguageAction():
            if state.language == action.language:
                return state
            return CompleteReducerResult(
                state=replace(state, language=action.language),
                events=[
                    LocalizationLanguageChangedEvent(language=action.language),
                ],
            )

        case LocalizationSetLocationAction():
            # A manually set location is authoritative — the automatic
            # IP-based detector never overwrites it.
            if (
                action.source is LocationSource.IP
                and state.location_source is LocationSource.MANUAL
            ):
                return state
            if (
                state.location == action.location
                and state.location_source == action.source
                and state.public_ip == action.public_ip
            ):
                return state
            return CompleteReducerResult(
                state=replace(
                    state,
                    location=action.location,
                    location_source=action.source,
                    public_ip=action.public_ip,
                    # The cached weather belongs to the previous location; if
                    # it's kept, its display fields still need refreshing —
                    # an AUTO-mode unit system tracks the country, and this
                    # may be the country changing.
                    weather=(
                        _recompute_weather_display(
                            state.weather,
                            state.unit_system,
                            action.location.country_code,
                        )
                        if state.location == action.location
                        else None
                    ),
                ),
                events=[
                    LocalizationLocationChangedEvent(
                        location=action.location,
                        source=action.source,
                    ),
                ],
            )

        case LocalizationResetLocationAction():
            return CompleteReducerResult(
                state=replace(
                    state,
                    location=None,
                    location_source=LocationSource.IP,
                    public_ip=None,
                    weather=None,
                ),
                events=[LocalizationLocationResetEvent()],
            )

        case LocalizationUpdateWeatherAction():
            return replace(
                state,
                weather=_recompute_weather_display(
                    action.weather,
                    state.unit_system,
                    state.location.country_code if state.location else None,
                ),
            )

        case LocalizationSetUnitSystemAction():
            if state.unit_system == action.unit_system:
                return state
            return CompleteReducerResult(
                state=replace(
                    state,
                    unit_system=action.unit_system,
                    weather=_recompute_weather_display(
                        state.weather,
                        action.unit_system,
                        state.location.country_code if state.location else None,
                    ),
                ),
                events=[
                    LocalizationUnitSystemChangedEvent(
                        unit_system=action.unit_system,
                    ),
                ],
            )

        case LocalizationUpdateClockAction():
            return replace(state, clock=action.clock, date=action.date)

        case LocalizationRefreshWeatherAction():
            if state.location is None:
                return state
            return CompleteReducerResult(
                state=state,
                events=[
                    LocalizationWeatherRefreshRequestedEvent(
                        location=state.location,
                    ),
                ],
            )

        case LocalizationSpeakTimeAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    LocalizationSpeakTimeEvent(
                        timezone=state.location.timezone if state.location else None,
                    ),
                ],
            )

        case LocalizationSpeakDateAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    LocalizationSpeakDateEvent(
                        timezone=state.location.timezone if state.location else None,
                    ),
                ],
            )

        case LocalizationSpeakWeatherAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    LocalizationSpeakWeatherEvent(
                        weather=state.weather,
                        location=state.location,
                    ),
                ],
            )

        case _:
            return state
