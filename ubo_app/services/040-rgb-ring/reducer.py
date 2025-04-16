# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.rgb_ring import (
    RgbRingAction,
    RgbRingCommandAction,
    RgbRingCommandEvent,
    RgbRingSetIsBusyAction,
    RgbRingState,
)

Action = InitAction | RgbRingAction


def reducer(
    state: RgbRingState | None,
    action: Action,
) -> ReducerResult[RgbRingState, Action, RgbRingCommandEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return RgbRingState(is_busy=False)
        raise InitializationActionError(action)

    if isinstance(action, RgbRingSetIsBusyAction):
        return replace(
            state,
            is_busy=action.is_busy,
        )

    if isinstance(action, RgbRingCommandAction):
        command = action.as_command()

        if not command:
            return state

        return CompleteReducerResult(
            state=state,
            events=[RgbRingCommandEvent(command=command.split())],
        )

    return state
