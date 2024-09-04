# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.users import (
    UsersAction,
    UsersCreateUserAction,
    UsersCreateUserEvent,
    UsersDeleteUserAction,
    UsersDeleteUserEvent,
    UsersEvent,
    UsersResetPasswordAction,
    UsersResetPasswordEvent,
    UsersSetUsersAction,
    UsersState,
)


def reducer(
    state: UsersState | None,
    action: UsersAction | InitAction,
) -> ReducerResult[UsersState, UsersAction, UsersEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return UsersState()
        raise InitializationActionError(action)

    if isinstance(action, UsersSetUsersAction):
        return replace(state, users=action.users)

    if isinstance(action, UsersCreateUserAction):
        return CompleteReducerResult(
            state=state,
            events=[UsersCreateUserEvent()],
        )

    if isinstance(action, UsersDeleteUserAction):
        return CompleteReducerResult(
            state=state,
            events=[UsersDeleteUserEvent(id=action.id)],
        )

    if isinstance(action, UsersResetPasswordAction):
        return CompleteReducerResult(
            state=state,
            events=[UsersResetPasswordEvent(id=action.id)],
        )

    return state
