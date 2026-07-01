# ruff: noqa: D100, D101
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class TailscaleAction(BaseAction): ...


class TailscaleEvent(BaseEvent): ...


class TailscaleStartDownloadingAction(TailscaleAction): ...


class TailscaleDoneDownloadingAction(TailscaleAction): ...


class TailscaleSetPendingAction(TailscaleAction): ...


class TailscaleSetStatusAction(TailscaleAction):
    is_installed: bool
    backend_state: str | None


class TailscaleState(Immutable):
    is_downloading: bool = False
    is_installed: bool | None = None
    is_active: bool = False
    backend_state: str | None = None
