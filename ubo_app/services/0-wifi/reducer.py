# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace
from distutils.util import strtobool
from typing import cast

from constants import WIFI_STATE_ICON_ID, WIFI_STATE_ICON_PRIORITY, get_signal_icon
from redux import (
    BaseAction,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.camera import CameraBarcodeAction, CameraStopViewFinderAction
from ubo_app.store.status_icons import StatusIconsRegisterAction
from ubo_app.store.wifi import (
    GlobalWiFiState,
    WiFiAction,
    WiFiConnection,
    WiFiCreateEvent,
    WiFiEvent,
    WiFiState,
    WiFiType,
    WiFiUpdateAction,
    WiFiUpdateRequestAction,
    WiFiUpdateRequestEvent,
)


def reducer(
    state: WiFiState | None,
    action: CameraBarcodeAction | WiFiAction,
) -> ReducerResult[WiFiState, BaseAction, WiFiEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return CompleteReducerResult(
                state=WiFiState(
                    connections=[],
                    state=GlobalWiFiState.UNKNOWN,
                    current_connection=None,
                ),
                actions=[WiFiUpdateRequestAction()],
            )
        raise InitializationActionError

    if isinstance(action, CameraBarcodeAction):
        ssid = action.match.get('SSID')
        if ssid is None:
            return state

        return CompleteReducerResult(
            state=state,
            actions=[CameraStopViewFinderAction()],
            events=[
                WiFiCreateEvent(
                    connection=WiFiConnection(
                        ssid=ssid,
                        password=action.match.get('Password'),
                        type=cast(WiFiType, action.match.get('Type')),
                        hidden=strtobool(
                            action.match.get('Hidden') or 'false',
                        )
                        == 1,
                    ),
                ),
            ],
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
                        GlobalWiFiState.CONNECTED: get_signal_icon(
                            action.current_connection.signal_strength
                            if action.current_connection
                            else 0,
                        ),
                        GlobalWiFiState.DISCONNECTED: 'signal_wifi_off',
                        GlobalWiFiState.PENDING: 'wifi_find',
                        GlobalWiFiState.NEEDS_ATTENTION: (
                            'signal_wifi_statusbar_not_connected'
                        ),
                        GlobalWiFiState.UNKNOWN: 'perm_scan_wifi',
                    }[action.state],
                    priority=WIFI_STATE_ICON_PRIORITY,
                    id=WIFI_STATE_ICON_ID,
                ),
            ],
        )

    return state
