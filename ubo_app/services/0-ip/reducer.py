# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from redux import (
    Action,
    BaseEvent,
    Immutable,
    InitAction,
    InitializationActionError,
    ReducerResult,
)


class IPState(Immutable):
    ...


def reducer(
    state: IPState | None,
    action: Action,
) -> ReducerResult[IPState, Action, BaseEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return IPState()
        raise InitializationActionError
    return state
