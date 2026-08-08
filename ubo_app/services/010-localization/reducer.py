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
    LocalizationSpeakDateAction,
    LocalizationSpeakDateEvent,
    LocalizationSpeakTimeAction,
    LocalizationSpeakTimeEvent,
    LocalizationSpeakWeatherAction,
    LocalizationSpeakWeatherEvent,
    LocalizationState,
    LocalizationUpdateClockAction,
    LocalizationUpdateWeatherAction,
    LocalizationWeatherRefreshRequestedEvent,
    LocationSource,
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
                    # The cached weather belongs to the previous location.
                    weather=(
                        state.weather
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
            return replace(state, weather=action.weather)

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
