# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class UsersAction(BaseAction): ...


class UsersSetUsersAction(UsersAction):
    users: list[UserState]


class UsersCreateUserAction(UsersAction): ...


class UsersDeleteUserAction(UsersAction):
    id: str


class UsersResetPasswordAction(UsersAction):
    id: str


class UsersEvent(BaseEvent): ...


class UsersCreateUserEvent(UsersEvent): ...


class UsersDeleteUserEvent(UsersEvent):
    id: str


class UsersResetPasswordEvent(UsersEvent):
    id: str


class UserState(Immutable):
    id: str
    is_removable: bool


class UsersState(Immutable):
    users: list[UserState] | None = None
