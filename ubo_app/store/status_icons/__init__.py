# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import Sequence

from immutable import Immutable
from redux import BaseAction


class IconState(Immutable):
    symbol: str
    color: str
    priority: int
    id: str | None


class StatusIconsState(Immutable):
    icons: Sequence[IconState]


class StatusIconsAction(BaseAction):
    ...


class StatusIconsRegisterAction(StatusIconsAction):
    icon: str
    color: str = 'white'
    priority: int = 0
    id: str | None = None
