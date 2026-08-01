"""Tests for the Wyoming service reducer."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from redux import InitAction

if TYPE_CHECKING:
    from collections.abc import Callable


def _import_types_and_reducer() -> tuple[tuple[Any, ...], Callable[..., Any]]:
    """Load service-local reducer code with its matching store classes."""
    modules_before = set(sys.modules)
    from ubo_app.store.services.wyoming import (
        WyomingConnectionPolicy,
        WyomingEnginesStatus,
        WyomingReportEnginesStatusAction,
        WyomingReportSatelliteStatusAction,
        WyomingSatelliteStatus,
        WyomingSatelliteWakeAction,
        WyomingSatelliteWakeEvent,
        WyomingSetAllowedPeersAction,
        WyomingSetConnectionPolicyAction,
        WyomingSetEnginesEnabledAction,
        WyomingSetSatelliteEnabledAction,
        WyomingState,
    )

    service_dir = str(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # type: ignore[import-not-found]

    for module in set(sys.modules) - modules_before:
        del sys.modules[module]

    return (
        WyomingConnectionPolicy,
        WyomingEnginesStatus,
        WyomingReportEnginesStatusAction,
        WyomingReportSatelliteStatusAction,
        WyomingSatelliteStatus,
        WyomingSatelliteWakeAction,
        WyomingSatelliteWakeEvent,
        WyomingSetAllowedPeersAction,
        WyomingSetConnectionPolicyAction,
        WyomingSetEnginesEnabledAction,
        WyomingSetSatelliteEnabledAction,
        WyomingState,
    ), reducer


(
    (
        WyomingConnectionPolicy,
        WyomingEnginesStatus,
        WyomingReportEnginesStatusAction,
        WyomingReportSatelliteStatusAction,
        WyomingSatelliteStatus,
        WyomingSatelliteWakeAction,
        WyomingSatelliteWakeEvent,
        WyomingSetAllowedPeersAction,
        WyomingSetConnectionPolicyAction,
        WyomingSetEnginesEnabledAction,
        WyomingSetSatelliteEnabledAction,
        WyomingState,
    ),
    reducer,
) = _import_types_and_reducer()


def test_initialization_uses_safe_local_defaults() -> None:
    """Wyoming is disabled and localhost-only until the user opts in."""
    state = reducer(None, InitAction())

    assert isinstance(state, WyomingState)
    assert state.is_satellite_enabled is False
    assert state.is_engines_enabled is False
    assert state.connection_policy is WyomingConnectionPolicy.LOCAL_ONLY
    assert state.allowed_peers == ()


def test_settings_actions_replace_immutable_state() -> None:
    """Configuration actions update only their intended state fields."""
    state = reducer(None, InitAction())

    enabled = reducer(state, WyomingSetSatelliteEnabledAction(enabled=True))
    engines = reducer(enabled, WyomingSetEnginesEnabledAction(enabled=True))
    policy = reducer(
        engines,
        WyomingSetConnectionPolicyAction(
            policy=WyomingConnectionPolicy.ALLOWLIST,
        ),
    )

    assert state.is_satellite_enabled is False
    assert enabled.is_satellite_enabled is True
    assert engines.is_engines_enabled is True
    assert policy.connection_policy is WyomingConnectionPolicy.ALLOWLIST


def test_allowed_peers_are_normalized_and_invalid_entries_are_rejected() -> None:
    """The persisted allowlist cannot accidentally broaden network access."""
    state = reducer(None, InitAction())

    updated = reducer(
        state,
        WyomingSetAllowedPeersAction(
            peers=['192.168.1.20', '10.0.0.0/24', '192.168.1.20', 'bad-host'],
        ),
    )

    assert updated.allowed_peers == ('10.0.0.0/24', '192.168.1.20')


def test_runtime_reports_do_not_affect_persisted_configuration() -> None:
    """Connection status remains runtime-only and serializable."""
    state = reducer(None, InitAction())

    streaming = reducer(
        state,
        WyomingReportSatelliteStatusAction(
            status=WyomingSatelliteStatus.STREAMING,
            client='192.168.1.20',
        ),
    )
    busy = reducer(
        streaming,
        WyomingReportEnginesStatusAction(
            status=WyomingEnginesStatus.BUSY,
            active_requests=2,
        ),
    )

    assert busy.satellite_status is WyomingSatelliteStatus.STREAMING
    assert busy.satellite_client == '192.168.1.20'
    assert busy.active_engine_requests == 2
    assert busy.connection_policy is WyomingConnectionPolicy.LOCAL_ONLY


def test_local_wake_word_emits_an_event_without_touching_configuration() -> None:
    """A wake hand-off is a runtime signal, not a settings change."""
    state = reducer(None, InitAction())

    result = reducer(
        state,
        WyomingSatelliteWakeAction(phrase='hey home assistant', detector='vosk'),
    )

    assert result.state == state
    assert len(result.events) == 1
    event = result.events[0]
    assert isinstance(event, WyomingSatelliteWakeEvent)
    assert event.phrase == 'hey home assistant'
    assert event.detector == 'vosk'
