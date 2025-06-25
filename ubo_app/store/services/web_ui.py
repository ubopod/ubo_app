# ruff: noqa: D100, D101
from __future__ import annotations

from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseEvent

if TYPE_CHECKING:
    from ubo_app.store.input.types import WebUIInputDescription


class WebUIEvent(BaseEvent): ...


class WebUIInitializeEvent(WebUIEvent):
    description: WebUIInputDescription


class WebUIStopEvent(WebUIEvent): ...


class WebUIState(Immutable):
    active_inputs: list[WebUIInputDescription]
