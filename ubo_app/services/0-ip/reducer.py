# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    Action,
    BaseEvent,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.ip import IpState, IpUpdateRequestAction, IpUpdateRequestEvent


def reducer(
    state: IpState | None,
    action: Action,
) -> ReducerResult[IpState, Action, BaseEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return IpState(interfaces=[])
        raise InitializationActionError

    if isinstance(action, IpUpdateRequestAction):
        return CompleteReducerResult(
            state=replace(state, status=None) if action.reset else state,
            events=[IpUpdateRequestEvent()],
        )
    return state
