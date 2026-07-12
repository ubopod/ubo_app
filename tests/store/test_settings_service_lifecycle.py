"""Reducer tests for settings-service lifecycle and configuration changes."""

from __future__ import annotations

from typing import cast

from redux import CompleteReducerResult

from ubo_app.store.settings.reducer import reducer
from ubo_app.store.settings.types import (
    ErrorReport,
    ServicesStatus,
    ServiceState,
    SettingsClearServiceErrorsAction,
    SettingsReportServiceErrorAction,
    SettingsServiceSetIsEnabledAction,
    SettingsServiceSetLogLevelAction,
    SettingsServiceSetShouldRestartAction,
    SettingsServiceSetStatusAction,
    SettingsSetServicesAction,
    SettingsStartServiceAction,
    SettingsStartServiceEvent,
    SettingsState,
    SettingsStopServiceAction,
    SettingsStopServiceEvent,
)


def _service(
    service_id: str,
    *,
    active: bool = False,
    enabled: bool = True,
    restart: bool = False,
) -> ServiceState:
    """Build a concise service-state fixture."""
    return ServiceState(
        id=service_id,
        label=service_id.title(),
        is_active=active,
        is_enabled=enabled,
        log_level=20,
        should_auto_restart=restart,
    )


def test_set_services_staggers_enabled_service_start_events() -> None:
    """Only enabled services start, in deterministic staggered order."""
    services = {
        'first': _service('first'),
        'disabled': _service('disabled', enabled=False),
        'second': _service('second'),
    }

    result = reducer(
        SettingsState(),
        SettingsSetServicesAction(services=services, gap_duration=0.5),
    )

    assert isinstance(result, CompleteReducerResult)
    assert result.state.services == services
    assert result.events == [
        SettingsStartServiceEvent(service_id='first', delay=0),
        SettingsStartServiceEvent(service_id='second', delay=0.5),
    ]


def test_service_status_restarts_active_service_and_tracks_readiness() -> None:
    """A failed active restartable service schedules recovery and leaves LOADING."""
    state = SettingsState(
        services={
            'restartable': _service('restartable', active=True, restart=True),
            'other': _service('other', active=True),
        },
    )

    result = reducer(
        state,
        SettingsServiceSetStatusAction(service_id='restartable', is_active=False),
    )

    assert isinstance(result, CompleteReducerResult)
    assert result.state.services['restartable'].is_active is False
    assert result.state.services_status == ServicesStatus.LOADING
    assert result.events == [
        SettingsStartServiceEvent(service_id='restartable', delay=2),
    ]


def test_service_status_becomes_ready_when_every_service_is_active() -> None:
    """The final active service transitions aggregate readiness to READY."""
    state = SettingsState(
        services={
            'ready': _service('ready', active=True),
            'starting': _service('starting', active=False),
        },
    )

    result = reducer(
        state,
        SettingsServiceSetStatusAction(service_id='starting', is_active=True),
    )

    assert isinstance(result, CompleteReducerResult)
    assert result.state.services_status == ServicesStatus.READY
    assert result.events == []


def test_service_configuration_and_errors_update_only_target_service() -> None:
    """Errors sort deterministically and service controls preserve other entries."""
    state = SettingsState(
        services={
            'target': _service('target'),
            'other': _service('other'),
        },
    )
    first = ErrorReport(timestamp=2, message='zebra')
    second = ErrorReport(timestamp=1, message='alpha')

    state = reducer(
        state,
        SettingsReportServiceErrorAction(service_id='target', error=first),
    )
    assert isinstance(state, SettingsState)
    state = reducer(
        state,
        SettingsReportServiceErrorAction(service_id='target', error=second),
    )
    assert isinstance(state, SettingsState)
    assert [error.message for error in state.services['target'].errors] == [
        'alpha',
        'zebra',
    ]

    state = reducer(
        state,
        SettingsServiceSetIsEnabledAction(service_id='target', is_enabled=False),
    )
    assert isinstance(state, SettingsState)
    state = reducer(
        state,
        SettingsServiceSetLogLevelAction(service_id='target', log_level=10),
    )
    assert isinstance(state, SettingsState)
    state = reducer(
        state,
        SettingsServiceSetShouldRestartAction(
            service_id='target',
            should_auto_restart=True,
        ),
    )
    assert isinstance(state, SettingsState)
    state = reducer(state, SettingsClearServiceErrorsAction(service_id='target'))

    assert isinstance(state, SettingsState)
    target = state.services['target']
    assert target.is_enabled is False
    assert target.log_level == 10
    assert target.should_auto_restart is True
    assert target.errors == []
    assert state.services['other'] == _service('other')


def test_start_and_stop_actions_emit_service_events() -> None:
    """Explicit service controls stay side-effect-free in the reducer."""
    state = SettingsState()

    start_result = reducer(state, SettingsStartServiceAction(service_id='service'))
    stop_result = reducer(state, SettingsStopServiceAction(service_id='service'))

    assert isinstance(start_result, CompleteReducerResult)
    assert start_result.events == [SettingsStartServiceEvent(service_id='service')]
    assert isinstance(stop_result, CompleteReducerResult)
    assert stop_result.events == [SettingsStopServiceEvent(service_id='service')]


def test_none_state_init_and_raise() -> None:
    """InitAction builds state; any other action against None raises."""
    import pytest
    from redux import InitAction, InitializationActionError

    from ubo_app.store.settings.types import SettingsToggleVisualDebugAction

    assert isinstance(reducer(None, InitAction()), SettingsState)
    with pytest.raises(InitializationActionError):
        reducer(None, SettingsToggleVisualDebugAction())


def test_toggle_pdb_signal_notifies_only_when_enabling() -> None:
    """Enabling the PDB signal posts instructions; disabling stays quiet."""
    from ubo_app.store.settings.types import SettingsTogglePdbSignalAction

    # Read the action type off the reducer's own module generation: an earlier
    # integration test may have reloaded ``notifications``, and a stale runtime
    # import here would not be the class the reducer actually emits.
    notifications_add_action = reducer.__globals__['NotificationsAddAction']

    enabling = cast(
        'CompleteReducerResult',
        reducer(SettingsState(pdb_signal=False), SettingsTogglePdbSignalAction()),
    )
    assert enabling.state.pdb_signal is True
    assert any(
        isinstance(action, notifications_add_action)
        for action in (enabling.actions or [])
    )

    disabling = cast(
        'CompleteReducerResult',
        reducer(SettingsState(pdb_signal=True), SettingsTogglePdbSignalAction()),
    )
    assert disabling.state.pdb_signal is False
    assert not disabling.actions


def test_toggle_visual_debug_flips_flag() -> None:
    """Visual-debug toggles its flag with no side effects."""
    from ubo_app.store.settings.types import SettingsToggleVisualDebugAction

    # No side effects, so this branch returns the bare state.
    result = cast(
        'SettingsState',
        reducer(
            SettingsState(visual_debug=False),
            SettingsToggleVisualDebugAction(),
        ),
    )
    assert result.visual_debug is True


def test_toggle_beta_versions_triggers_update_check() -> None:
    """Toggling beta versions flips the flag and re-checks for updates."""
    from ubo_app.store.settings.types import SettingsToggleBetaVersionsAction

    update_check_action = reducer.__globals__['UpdateManagerRequestCheckAction']

    result = cast(
        'CompleteReducerResult',
        reducer(
            SettingsState(beta_versions=False),
            SettingsToggleBetaVersionsAction(),
        ),
    )
    assert result.state.beta_versions is True
    assert any(
        isinstance(action, update_check_action)
        for action in (result.actions or [])
    )


def test_set_status_for_unknown_service_is_noop() -> None:
    """Setting status for an id absent from a populated registry is a no-op."""
    state = SettingsState(services={'known': _service('known')})
    result = reducer(
        state,
        SettingsServiceSetStatusAction(service_id='ghost', is_active=True),
    )
    assert result is state
