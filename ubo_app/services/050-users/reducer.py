# ruff: noqa: D100, D103
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

    match action:
        case UsersSetUsersAction():
            return replace(state, users=action.users)

        case UsersCreateUserAction():
            return CompleteReducerResult(
                state=state,
                events=[UsersCreateUserEvent()],
            )

        case UsersDeleteUserAction():
            return CompleteReducerResult(
                state=state,
                events=[UsersDeleteUserEvent(id=action.id)],
            )

        case UsersResetPasswordAction():
            return CompleteReducerResult(
                state=state,
                events=[UsersResetPasswordEvent(id=action.id)],
            )

        case _:
            return state
