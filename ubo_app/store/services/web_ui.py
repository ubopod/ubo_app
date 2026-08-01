# ruff: noqa: D100, D101
from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from ubo_app.store.input.types import WebUIInputDescription


class WebUIAction(BaseAction): ...


class WebUIEvent(BaseEvent): ...


class WebUIInitializeEvent(WebUIEvent):
    description: WebUIInputDescription


class WebUIInputCommand(StrEnum):
    UP = 'up'
    DOWN = 'down'
    LEFT = 'left'
    RIGHT = 'right'
    SELECT = 'select'
    BACK = 'back'
    HOME = 'home'


class WebUIInputAction(WebUIAction):
    command: WebUIInputCommand


class WebUIInputEvent(WebUIEvent):
    command: WebUIInputCommand


class WebUIState(Immutable):
    active_inputs: list[WebUIInputDescription]
