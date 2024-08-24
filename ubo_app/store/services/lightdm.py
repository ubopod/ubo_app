# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction


class LightDMAction(BaseAction): ...


class LightDMUpdateStateAction(LightDMAction):
    is_active: bool | None = None
    is_enabled: bool | None = None
    is_installed: bool | None = None
    is_installing: bool | None = None


class LightDMClearEnabledStateAction(LightDMAction): ...


class LightDMState(Immutable):
    is_active: bool = False
    is_enabled: bool = False
    is_installed: bool = False
    is_installing: bool = False
