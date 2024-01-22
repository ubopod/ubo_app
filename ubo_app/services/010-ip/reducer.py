# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.ip import (
    IpState,
    IpUpdateAction,
    IpUpdateRequestAction,
    IpUpdateRequestEvent,
)

Action = InitAction | IpUpdateAction | IpUpdateRequestAction
ResultEvent = IpUpdateRequestEvent


def reducer(
    state: IpState | None,
    action: Action,
) -> ReducerResult[IpState, Action, ResultEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return IpState(interfaces=[])
        raise InitializationActionError(action)

    if isinstance(action, IpUpdateAction):
        return replace(state, interfaces=action.interfaces)

    if isinstance(action, IpUpdateRequestAction):
        return CompleteReducerResult(
            state=replace(state, status=None) if action.reset else state,
            events=[IpUpdateRequestEvent()],
        )
    return state
