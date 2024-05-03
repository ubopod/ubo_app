# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction


class VSCodeAction(BaseAction): ...


class VSCodeStartDownloadingAction(VSCodeAction): ...


class VSCodeDoneDownloadingAction(VSCodeAction): ...


class VSCodeStatus(Immutable):
    is_service_installed: bool
    is_running: bool
    name: str | None


class VSCodeSetStatusAction(VSCodeAction):
    timestamp: float

    is_binary_installed: bool
    is_logged_in: bool
    status: VSCodeStatus | None


class VSCodeState(Immutable):
    last_update_timestamp: float = 0

    is_downloading: bool = False
    is_binary_installed: bool = False
    is_logged_in: bool = False
    status: VSCodeStatus | None = None
