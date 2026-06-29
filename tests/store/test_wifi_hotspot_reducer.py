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
