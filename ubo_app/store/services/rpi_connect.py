# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class RPiConnectAction(BaseAction): ...


class RPiConnectEvent(BaseEvent): ...


class RPiConnectStartDownloadingAction(RPiConnectAction): ...


class RPiConnectDoneDownloadingAction(RPiConnectAction): ...


class RPiConnectSetPendingAction(RPiConnectAction): ...


class RPiConnectStatus(Immutable):
    screen_sharing_sessions: int | None
    remote_shell_sessions: int | None


class RPiConnectSetStatusAction(RPiConnectAction):
    is_installed: bool
    is_signed_in: bool | None
    status: RPiConnectStatus | None


class RPiConnectLoginEvent(RPiConnectEvent): ...


class RPiConnectUpdateServiceStateAction(RPiConnectAction):
    is_active: bool | None = None


class RPiConnectState(Immutable):
    is_downloading: bool = False
    is_active: bool = False
    is_installed: bool | None = None
    is_signed_in: bool | None = None
    status: RPiConnectStatus | None = None
