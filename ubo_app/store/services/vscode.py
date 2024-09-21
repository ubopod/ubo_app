# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class VSCodeAction(BaseAction): ...


class VSCodeEvent(BaseEvent): ...


class VSCodeStartDownloadingAction(VSCodeAction): ...


class VSCodeDoneDownloadingAction(VSCodeAction): ...


class VSCodeSetPendingAction(VSCodeAction): ...


class VSCodeStatus(Immutable):
    is_service_installed: bool
    is_running: bool
    name: str | None


class VSCodeSetStatusAction(VSCodeAction):
    is_binary_installed: bool
    is_logged_in: bool
    status: VSCodeStatus | None


class VSCodeLoginEvent(VSCodeEvent): ...


class VSCodeRestartEvent(VSCodeEvent): ...


class VSCodeState(Immutable):
    is_pending: bool = True
    is_downloading: bool = False
    is_binary_installed: bool = False
    is_logged_in: bool | None = None
    status: VSCodeStatus | None = None
