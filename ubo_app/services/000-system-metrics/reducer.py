# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import BaseEvent, InitAction, InitializationActionError, ReducerResult

from ubo_app.store.services.system import (
    SystemAction,
    SystemMetricsUpdateAction,
    SystemState,
)

Action = InitAction | SystemAction


def reducer(
    state: SystemState | None,
    action: Action,
) -> ReducerResult[SystemState, Action, BaseEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return SystemState()
        raise InitializationActionError(action)

    match action:
        case SystemMetricsUpdateAction():
            return replace(
                state,
                cpu_percent=action.cpu_percent,
                ram_percent=action.ram_percent,
                clock=action.clock,
            )
        case _:
            return state
