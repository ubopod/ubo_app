# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import (
    BaseAction,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.ethernet import NetState
from ubo_app.store.services.wifi import (
    WiFiAction,
    WiFiEvent,
    WiFiInputConnectionAction,
    WiFiInputConnectionEvent,
    WiFiSetHasVisitedOnboardingAction,
    WiFiSetHotspotRunningAction,
    WiFiStartHotspotAction,
    WiFiStartHotspotEvent,
    WiFiState,
    WiFiStopHotspotAction,
    WiFiStopHotspotEvent,
    WiFiUpdateAction,
    WiFiUpdateRequestAction,
    WiFiUpdateRequestEvent,
)


def reducer(
    state: WiFiState | None,
    action: WiFiAction,
) -> ReducerResult[WiFiState, BaseAction, WiFiEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return CompleteReducerResult(
                state=WiFiState(
                    connections=[],
                    state=NetState.UNKNOWN,
                    current_connection=None,
                ),
                actions=[WiFiUpdateRequestAction()],
            )
        raise InitializationActionError(action)

    match action:
        case WiFiInputConnectionAction():
            return CompleteReducerResult(
                state=state,
                events=[WiFiInputConnectionEvent()],
            )

        case WiFiSetHasVisitedOnboardingAction():
            return CompleteReducerResult(
                state=replace(
                    state,
                    has_visited_onboarding=action.has_visited_onboarding,
                ),
                events=[WiFiUpdateRequestEvent()],
            )

        case WiFiUpdateRequestAction():
            return CompleteReducerResult(
                state=replace(state, connections=None) if action.reset else state,
                events=[WiFiUpdateRequestEvent()],
            )

        case WiFiUpdateAction():
            # The status-bar icon is registered by an autorun in pages/main.py so
            # it can also reflect hotspot (AP) mode, which this slice owns via
            # ``is_hotspot_running`` below.
            return replace(
                state,
                connections=action.connections,
                state=action.state,
                current_connection=action.current_connection,
            )

        case WiFiStartHotspotAction(mode=mode):
            return CompleteReducerResult(
                state=state,
                events=[WiFiStartHotspotEvent(mode=mode)],
            )

        case WiFiStopHotspotAction():
            return CompleteReducerResult(
                state=state,
                events=[WiFiStopHotspotEvent()],
            )

        case WiFiSetHotspotRunningAction(
            is_running=is_running,
            user_enabled=user_enabled,
        ):
            return replace(
                state,
                is_hotspot_running=is_running,
                hotspot_user_enabled=user_enabled,
            )

        case _:
            return state

    return state
