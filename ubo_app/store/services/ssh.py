# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction


class SSHAction(BaseAction): ...


class SSHUpdateStateAction(SSHAction):
    is_active: bool | None = None
    is_enabled: bool | None = None


class SSHState(Immutable):
    is_active: bool = False
    is_enabled: bool = False
