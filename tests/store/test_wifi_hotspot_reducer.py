"""Tests for the wifi reducer's hotspot lifecycle.

The hotspot (wlan0 in AP mode) is owned by the wifi service: the reducer turns
``WiFiStartHotspotAction``/``WiFiStopHotspotAction`` into the corresponding
events (handled by the side-effect layer that talks to the system manager) and
tracks ``is_hotspot_running``/``hotspot_user_enabled`` via
``WiFiSetHotspotRunningAction``.

Uses the same ``sys.path`` loader discipline as ``test_web_ui_reducer.py`` so the
reducer's match-case and the test's constructed actions reference the same class
objects even after an integration test wipes ``sys.modules``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from redux import CompleteReducerResult

from ubo_app.store.services.ethernet import NetState

if TYPE_CHECKING:
    from collections.abc import Callable


def _import_types_and_reducer() -> tuple[tuple[Any, ...], Callable[..., Any]]:
    modules_before = set(sys.modules)

    from ubo_app.store.services.wifi import (
        WiFiSetHotspotRunningAction,
        WiFiStartHotspotAction,
        WiFiStartHotspotEvent,
        WiFiState,
        WiFiStopHotspotAction,
        WiFiStopHotspotEvent,
    )

    service_dir = str(
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '030-wifi',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # type: ignore[import-not-found]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return (
        WiFiSetHotspotRunningAction,
        WiFiStartHotspotAction,
        WiFiStartHotspotEvent,
        WiFiState,
        WiFiStopHotspotAction,
        WiFiStopHotspotEvent,
    ), reducer


(
    WiFiSetHotspotRunningAction,
    WiFiStartHotspotAction,
    WiFiStartHotspotEvent,
    WiFiState,
    WiFiStopHotspotAction,
    WiFiStopHotspotEvent,
), reducer = _import_types_and_reducer()


def _state() -> object:
    return WiFiState(
        connections=[],
        state=NetState.UNKNOWN,
        current_connection=None,
    )


def test_start_action_threads_mode_into_event() -> None:
    """WiFiStartHotspotAction(mode) emits WiFiStartHotspotEvent with that mode."""
    result = reducer(_state(), WiFiStartHotspotAction(mode='share'))

    assert isinstance(result, CompleteReducerResult)
    start_events = [
        event
        for event in result.events or []
        if isinstance(event, WiFiStartHotspotEvent)
    ]
    assert start_events
    assert start_events[0].mode == 'share'


def test_stop_action_emits_stop_event() -> None:
    """WiFiStopHotspotAction emits WiFiStopHotspotEvent (the only teardown path)."""
    result = reducer(_state(), WiFiStopHotspotAction())

    assert isinstance(result, CompleteReducerResult)
    assert any(isinstance(event, WiFiStopHotspotEvent) for event in result.events or [])


def test_set_running_tracks_user_enabled() -> None:
    """WiFiSetHotspotRunningAction syncs both running and user-enabled flags."""
    result = reducer(
        _state(),
        WiFiSetHotspotRunningAction(is_running=True, user_enabled=True),
    )

    new_state = result.state if isinstance(result, CompleteReducerResult) else result
    assert new_state.is_hotspot_running is True
    assert new_state.hotspot_user_enabled is True


def _g(name: str) -> Any:  # noqa: ANN401
    """Fetch a symbol the reducer imported, guaranteeing one module generation."""
    return reducer.__globals__[name]


def test_none_state_init_requests_update_and_non_init_raises() -> None:
    """InitAction builds state and kicks off an update; else it raises."""
    result = reducer(None, _g('InitAction')())
    assert isinstance(result, CompleteReducerResult)
    assert any(
        isinstance(action, _g('WiFiUpdateRequestAction'))
        for action in (result.actions or [])
    )
    with pytest.raises(_g('InitializationActionError')):
        reducer(None, _g('WiFiStopHotspotAction')())


def test_input_connection_emits_event() -> None:
    """WiFiInputConnectionAction emits its input-connection event."""
    result = reducer(_state(), _g('WiFiInputConnectionAction')())
    assert any(
        isinstance(event, _g('WiFiInputConnectionEvent'))
        for event in (result.events or [])
    )


def test_set_has_visited_onboarding_updates_and_requests_refresh() -> None:
    """Onboarding-visited flips the flag and requests a refresh."""
    result = reducer(
        _state(),
        _g('WiFiSetHasVisitedOnboardingAction')(has_visited_onboarding=True),
    )
    assert result.state.has_visited_onboarding is True
    assert any(
        isinstance(event, _g('WiFiUpdateRequestEvent'))
        for event in (result.events or [])
    )


def test_update_request_reset_clears_connections() -> None:
    """A reset update-request wipes the cached connections before refreshing."""
    state = _state()
    request = _g('WiFiUpdateRequestAction')

    plain = reducer(state, request(reset=False))
    assert plain.state is state

    reset = reducer(state, request(reset=True))
    assert reset.state.connections is None


def test_update_action_replaces_connection_snapshot() -> None:
    """WiFiUpdateAction overwrites the connection list, state, and current."""
    result = reducer(
        _state(),
        _g('WiFiUpdateAction')(
            connections=[],
            state=NetState.CONNECTED,
            current_connection=None,
        ),
    )
    new_state = result.state if isinstance(result, CompleteReducerResult) else result
    assert new_state.state == NetState.CONNECTED


def test_unknown_action_returns_state_unchanged() -> None:
    """An action matching no case leaves the state untouched."""
    state = _state()
    assert reducer(state, _g('InitAction')()) is state
