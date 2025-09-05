# ruff: noqa: D100, D101
from __future__ import annotations

import time
from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction


class Key(StrEnum):
    BACK = 'Back'
    HOME = 'Home'
    UP = 'Up'
    DOWN = 'Down'
    L1 = 'L1'
    L2 = 'L2'
    L3 = 'L3'


class KeypadAction(BaseAction):
    key: Key
    pressed_keys: set[Key]
    held_keys: set[Key] = field(default_factory=set)
    time: float = field(default_factory=time.time)


class KeypadKeyPressAction(KeypadAction): ...


class KeypadKeyHoldAction(KeypadAction): ...


class KeypadKeyUnholdAction(KeypadAction): ...


class KeypadKeyReleaseAction(KeypadAction): ...


class KeypadState(Immutable):
    depth: int = 0
    is_consumed: bool = False
