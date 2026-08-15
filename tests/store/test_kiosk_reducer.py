"""Tests for the Browser Kiosk reducer.

The kiosk reducer mirrors the LightDM pattern (state merge + tri-state enabled)
and additionally emits ``KioskApplyConfigEvent`` whenever a port selection,
dashboard set, or rotation changes so the service can regenerate ``weston.ini``
and restart the unit.

The store types import normally; only the reducer needs a ``sys.path`` shim,
since the service directory (``055-kiosk``) is not an importable package. The
reducer binds to the already-loaded ``ubo_app.store.services.kiosk`` module, so
its match-case and this test share the same class objects.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitAction

from ubo_app.store.services.kiosk import (
    UBO_WEBUI_DASHBOARD_ID,
    KioskAction,
    KioskAddDashboardAction,
    KioskApplyConfigEvent,
    KioskClearEnabledStateAction,
    KioskDashboard,
    KioskDeleteDashboardAction,
    KioskPortRole,
    KioskPortSelection,
    KioskPortSelections,
    KioskRotatePortAction,
    KioskSetPortSelectionAction,
    KioskState,
    KioskUpdateStateAction,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    ReducerType = Callable[
        [KioskState | None, KioskAction | InitAction],
        KioskState
        | CompleteReducerResult[KioskState, KioskAction, KioskApplyConfigEvent],
    ]


def _import_reducer() -> ReducerType:
    """Import the service-dir ``reducer`` module via a ``sys.path`` shim.

    Records ``sys.modules`` before the import and drops anything newly loaded
    afterwards so integration/flow tests are unaffected by the bare ``reducer``
    module name.
    """
    modules_before = set(sys.modules)

    service_dir = str(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '055-kiosk',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # type: ignore[import-not-found]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return reducer


reducer: ReducerType = _import_reducer()


def test_init_action_returns_default_state() -> None:
    """A None state with InitAction yields the default KioskState."""
    state = reducer(None, InitAction())

    assert isinstance(state, KioskState)
    assert state.is_active is False
    assert state.is_installed is False
    assert state.port_selections.hdmi_a_1.role == KioskPortRole.BROWSER
    assert state.port_selections.hdmi_a_1.dashboard_id == UBO_WEBUI_DASHBOARD_ID
    assert state.port_selections.hdmi_a_2.role == KioskPortRole.TERMINAL
    # The built-in Ubo WebUI dashboard is always present.
    assert state.dashboards[0].id == UBO_WEBUI_DASHBOARD_ID


def test_update_state_action_merges_provided_fields() -> None:
    """Only non-None fields on the action are merged into the state."""
    state = KioskState()

    result = reducer(
        state,
        KioskUpdateStateAction(is_installed=True, is_active=True),
    )

    assert isinstance(result, KioskState)
    assert result.is_installed is True
    assert result.is_active is True
    # Untouched fields keep their previous values.
    assert result.is_enabled is False
    assert result.is_installing is False


def test_clear_enabled_state_action_sets_enabled_none() -> None:
    """The tri-state 'loading' value is represented by is_enabled=None."""
    state = KioskState(is_enabled=True)

    result = reducer(state, KioskClearEnabledStateAction())

    assert isinstance(result, KioskState)
    assert result.is_enabled is None


def test_set_port_selection_action_updates_and_emits_event() -> None:
    """Changing a port selection updates state and emits KioskApplyConfigEvent."""
    state = KioskState()

    result = reducer(
        state,
        KioskSetPortSelectionAction(port='hdmi_a_1', role=KioskPortRole.OFF),
    )

    assert isinstance(result, CompleteReducerResult)
    assert result.state.port_selections.hdmi_a_1.role == KioskPortRole.OFF
    # The other port is left untouched.
    assert result.state.port_selections.hdmi_a_2.role == KioskPortRole.TERMINAL
    events = list(result.events or [])
    assert len(events) == 1
    assert isinstance(events[0], KioskApplyConfigEvent)


def test_add_dashboard_appends_without_event() -> None:
    """Adding a dashboard grows the set and emits no config event."""
    state = KioskState()

    result = reducer(
        state,
        KioskAddDashboardAction(id='ha', name='HA Dashboard', url='http://ha.local'),
    )

    assert isinstance(result, KioskState)
    assert result.dashboards[-1] == KioskDashboard(
        id='ha',
        name='HA Dashboard',
        url='http://ha.local',
    )


def test_delete_dashboard_removes_reverts_port_and_emits_event() -> None:
    """Deleting a dashboard drops it and reverts a pointing port to Terminal."""
    state = KioskState(
        dashboards=(
            KioskDashboard(id=UBO_WEBUI_DASHBOARD_ID, name='Ubo WebUI', url='u'),
            KioskDashboard(id='ha', name='HA Dashboard', url='http://ha.local'),
        ),
        port_selections=_with_port(
            KioskState(),
            'hdmi_a_1',
            KioskPortSelection(role=KioskPortRole.BROWSER, dashboard_id='ha'),
        ),
    )

    result = reducer(state, KioskDeleteDashboardAction(dashboard_id='ha'))

    assert isinstance(result, CompleteReducerResult)
    assert all(d.id != 'ha' for d in result.state.dashboards)
    assert result.state.port_selections.hdmi_a_1.role == KioskPortRole.TERMINAL
    events = list(result.events or [])
    assert len(events) == 1
    assert isinstance(events[0], KioskApplyConfigEvent)


def test_delete_builtin_dashboard_is_noop() -> None:
    """The built-in Ubo WebUI dashboard cannot be deleted."""
    state = KioskState()

    result = reducer(
        state,
        KioskDeleteDashboardAction(dashboard_id=UBO_WEBUI_DASHBOARD_ID),
    )

    assert result is state


def test_rotate_port_cycles_terminal_then_dashboards() -> None:
    """Rotate cycles Terminal -> Ubo WebUI -> user dashboard -> Terminal."""
    state = KioskState(
        dashboards=(
            KioskDashboard(id=UBO_WEBUI_DASHBOARD_ID, name='Ubo WebUI', url='u'),
            KioskDashboard(id='ha', name='HA Dashboard', url='http://ha.local'),
        ),
        port_selections=_with_port(
            KioskState(),
            'hdmi_a_1',
            KioskPortSelection(role=KioskPortRole.TERMINAL),
        ),
    )

    # Terminal -> first dashboard (Ubo WebUI)
    state = _rotate(state, 'hdmi_a_1')
    assert state.port_selections.hdmi_a_1.role == KioskPortRole.BROWSER
    assert state.port_selections.hdmi_a_1.dashboard_id == UBO_WEBUI_DASHBOARD_ID

    # -> second dashboard (HA)
    state = _rotate(state, 'hdmi_a_1')
    assert state.port_selections.hdmi_a_1.dashboard_id == 'ha'

    # -> back to Terminal
    state = _rotate(state, 'hdmi_a_1')
    assert state.port_selections.hdmi_a_1.role == KioskPortRole.TERMINAL


def _with_port(
    state: KioskState,
    port: str,
    selection: KioskPortSelection,
) -> KioskPortSelections:
    from dataclasses import replace

    return replace(state.port_selections, **{port: selection})


def _rotate(state: KioskState, port: str) -> KioskState:
    result = reducer(state, KioskRotatePortAction(port=port))
    assert isinstance(result, CompleteReducerResult)
    assert any(isinstance(e, KioskApplyConfigEvent) for e in result.events or [])
    return result.state
