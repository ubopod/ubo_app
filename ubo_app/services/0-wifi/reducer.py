# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace

from redux import (
    BaseAction,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.camera import CameraBarcodeAction, CameraStopViewFinderAction
from ubo_app.store.wifi import (
    WiFiAction,
    WiFiConnection,
    WiFiCreateEvent,
    WiFiCreateEventPayload,
    WiFiEvent,
    WiFiState,
    WiFiUpdateAction,
    WiFiUpdateEvent,
)


def reducer(
    state: WiFiState | None,
    action: CameraBarcodeAction | WiFiAction,
) -> ReducerResult[WiFiState, BaseAction, WiFiEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return CompleteReducerResult(
                state=WiFiState(connections=[], is_on=False, current_connection=None),
                events=[WiFiUpdateEvent()],
            )
        raise InitializationActionError

    if isinstance(action, CameraBarcodeAction):
        ssid = action.payload.match.get('SSID')
        if ssid is None:
            return state

        return CompleteReducerResult(
            state=state,
            actions=[CameraStopViewFinderAction()],
            events=[
                WiFiCreateEvent(
                    payload=WiFiCreateEventPayload(
                        connection=WiFiConnection(
                            ssid=ssid,
                            password=action.payload.match.get('Password'),
                            type=action.payload.match.get('Type'),
                        ),
                    ),
                ),
            ],
        )

    if isinstance(action, WiFiUpdateAction):
        return replace(
            state,
            connections=action.payload.connections,
            is_on=action.payload.is_on,
            current_connection=action.payload.current_connection,
        )

    return state
