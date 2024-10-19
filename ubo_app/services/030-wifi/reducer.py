# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace

from constants import WIFI_STATE_ICON_ID, WIFI_STATE_ICON_PRIORITY, get_signal_icon
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
    WiFiSetHasVisitedOnboardingAction,
    WiFiState,
    WiFiUpdateAction,
    WiFiUpdateRequestAction,
    WiFiUpdateRequestEvent,
)
from ubo_app.store.status_icons import StatusIconsRegisterAction


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

    if isinstance(action, WiFiSetHasVisitedOnboardingAction):
        return CompleteReducerResult(
            state=replace(state, has_visited_onboarding=action.has_visited_onboarding),
            events=[WiFiUpdateRequestEvent()],
        )

    if isinstance(action, WiFiUpdateRequestAction):
        return CompleteReducerResult(
            state=replace(state, connections=None) if action.reset else state,
            events=[WiFiUpdateRequestEvent()],
        )

    if isinstance(action, WiFiUpdateAction):
        return CompleteReducerResult(
            state=replace(
                state,
                connections=action.connections,
                state=action.state,
                current_connection=action.current_connection,
            ),
            actions=[
                StatusIconsRegisterAction(
                    icon={
                        NetState.CONNECTED: get_signal_icon(
                            action.current_connection.signal_strength
                            if action.current_connection
                            else 0,
                        ),
                        NetState.DISCONNECTED: '󰖪',
                        NetState.PENDING: '󱛇',
                        NetState.NEEDS_ATTENTION: '󱚵',
                        NetState.UNKNOWN: '󰈅',
                    }[action.state],
                    priority=WIFI_STATE_ICON_PRIORITY,
                    id=WIFI_STATE_ICON_ID,
                ),
            ],
        )

    return state
