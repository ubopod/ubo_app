# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from redux import BaseAction


class Key(str, Enum):
    BACK = 'Back'
    HOME = 'Home'
    UP = 'Up'
    DOWN = 'Down'
    L1 = 'L1'
    L2 = 'L2'
    L3 = 'L3'


@dataclass(frozen=True)
class KeypadActionPayload:
    key: Key


KeyActionType = Literal['KEYPAD_KEY_UP', 'KEYPAD_KEY_DOWN', 'KEYPAD_KEY_PRESS']


@dataclass(frozen=True)
class KeypadAction(BaseAction):
    payload: KeypadActionPayload
    type: KeyActionType


@dataclass(frozen=True)
class KeypadKeyUpAction(KeypadAction):
    type: Literal['KEYPAD_KEY_UP'] = 'KEYPAD_KEY_UP'


@dataclass(frozen=True)
class KeypadKeyDownAction(KeypadAction):
    type: Literal['KEYPAD_KEY_DOWN'] = 'KEYPAD_KEY_DOWN'


@dataclass(frozen=True)
class KeypadKeyPressAction(KeypadAction):
    type: Literal['KEYPAD_KEY_PRESS'] = 'KEYPAD_KEY_PRESS'


def dispatch_key(action: KeyActionType, key: Key) -> None:
    from ubo_app.store import dispatch

    cls: type[KeypadAction]

    if action == 'KEYPAD_KEY_DOWN':
        cls = KeypadKeyDownAction
    elif action == 'KEYPAD_KEY_UP':
        cls = KeypadKeyUpAction
    elif action == 'KEYPAD_KEY_PRESS':
        cls = KeypadKeyPressAction

    dispatch(cls(payload=KeypadActionPayload(key=key)))
