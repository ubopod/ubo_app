# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction

from ubo_app.store.core.types import service_default_factory

if TYPE_CHECKING:
    from collections.abc import Sequence


class IconState(Immutable):
    symbol: str
    color: str
    priority: int
    service_id: str
    id: str | None


class StatusIconsState(Immutable):
    icons: Sequence[IconState]


class StatusIconsAction(BaseAction): ...


class StatusIconsRegisterAction(StatusIconsAction):
    icon: str
    color: str = 'white'
    priority: int = 0
    id: str | None = None
    service: str | None = field(default_factory=service_default_factory)
