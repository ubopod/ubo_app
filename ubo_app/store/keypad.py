# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from enum import Enum

from redux import BaseAction, BaseEvent, Immutable


class Key(str, Enum):
    BACK = 'Back'
    HOME = 'Home'
    UP = 'Up'
    DOWN = 'Down'
    L1 = 'L1'
    L2 = 'L2'
    L3 = 'L3'


class KeypadActionPayload(Immutable):
    key: Key


class KeypadAction(BaseAction):
    payload: KeypadActionPayload


class KeypadKeyUpAction(KeypadAction):
    ...


class KeypadKeyDownAction(KeypadAction):
    ...


class KeypadKeyPressAction(KeypadAction):
    ...


class KeypadEventPayload(Immutable):
    key: Key


class KeypadEvent(BaseEvent):
    payload: KeypadEventPayload


class KeypadKeyPressEvent(KeypadEvent):
    ...
