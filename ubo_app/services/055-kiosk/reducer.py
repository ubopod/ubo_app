# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
)

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
    KioskRotatePortAction,
    KioskSetPortSelectionAction,
    KioskState,
    KioskUpdateStateAction,
)

_PORT_FIELDS = ('hdmi_a_1', 'hdmi_a_2')


def _rotation_cycle(
    dashboards: tuple[KioskDashboard, ...],
) -> list[KioskPortSelection]:
    """Ordered targets for the rotate action: Terminal then each dashboard."""
    return [
        KioskPortSelection(role=KioskPortRole.TERMINAL),
        *(
            KioskPortSelection(role=KioskPortRole.BROWSER, dashboard_id=dashboard.id)
            for dashboard in dashboards
        ),
    ]


def _rotation_index(
    selection: KioskPortSelection,
    cycle: list[KioskPortSelection],
) -> int:
    """Where the current selection sits in the cycle (non-matches map to 0)."""
    if selection.role == KioskPortRole.BROWSER:
        for index, target in enumerate(cycle):
            if (
                target.role == KioskPortRole.BROWSER
                and target.dashboard_id == selection.dashboard_id
            ):
                return index
    return 0


def reducer(
    state: KioskState | None,
    action: KioskAction | InitAction,
) -> KioskState | CompleteReducerResult[KioskState, KioskAction, KioskApplyConfigEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return KioskState()
        raise InitializationActionError(action)

    match action:
        case KioskClearEnabledStateAction():
            return replace(state, is_enabled=None)

        case KioskUpdateStateAction():
            if action.is_active is not None:
                state = replace(state, is_active=action.is_active)
            if action.is_enabled is not None:
                state = replace(state, is_enabled=action.is_enabled)
            if action.is_installed is not None:
                state = replace(state, is_installed=action.is_installed)
            if action.is_installing is not None:
                state = replace(state, is_installing=action.is_installing)
            if action.connected_ports is not None:
                state = replace(state, connected_ports=action.connected_ports)
            return state

        case KioskSetPortSelectionAction():
            selection = KioskPortSelection(
                role=action.role,
                dashboard_id=action.dashboard_id,
            )
            new_selections = replace(
                state.port_selections,
                **{action.port: selection},
            )
            return CompleteReducerResult(
                state=replace(state, port_selections=new_selections),
                events=[KioskApplyConfigEvent()],
            )

        case KioskAddDashboardAction():
            return replace(
                state,
                dashboards=(
                    *state.dashboards,
                    KioskDashboard(id=action.id, name=action.name, url=action.url),
                ),
            )

        case KioskDeleteDashboardAction():
            if action.dashboard_id == UBO_WEBUI_DASHBOARD_ID:
                return state
            dashboards = tuple(
                dashboard
                for dashboard in state.dashboards
                if dashboard.id != action.dashboard_id
            )
            selections = state.port_selections
            for field_name in _PORT_FIELDS:
                selection = getattr(selections, field_name)
                if (
                    selection.role == KioskPortRole.BROWSER
                    and selection.dashboard_id == action.dashboard_id
                ):
                    selections = replace(
                        selections,
                        **{field_name: KioskPortSelection(role=KioskPortRole.TERMINAL)},
                    )
            return CompleteReducerResult(
                state=replace(
                    state,
                    dashboards=dashboards,
                    port_selections=selections,
                ),
                events=[KioskApplyConfigEvent()],
            )

        case KioskRotatePortAction():
            cycle = _rotation_cycle(state.dashboards)
            current = getattr(state.port_selections, action.port)
            next_selection = cycle[(_rotation_index(current, cycle) + 1) % len(cycle)]
            new_selections = replace(
                state.port_selections,
                **{action.port: next_selection},
            )
            return CompleteReducerResult(
                state=replace(state, port_selections=new_selections),
                events=[KioskApplyConfigEvent()],
            )

        case _:
            return state
