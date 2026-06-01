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
    pressed_keys: tuple[Key, ...]
    held_keys: tuple[Key, ...] = ()
    time: float = field(default_factory=time.time)


class KeypadKeyPressAction(KeypadAction): ...


class KeypadKeyHoldAction(KeypadAction): ...


class KeypadKeyUnholdAction(KeypadAction): ...


class KeypadKeyReleaseAction(KeypadAction): ...


class KeypadReportContextAction(BaseAction):
    """Mirror cross-slice UI context into the keypad slice.

    Dispatched by the keypad service's autorun whenever the navigation/display context
    changes, so the keypad reducer can stay pure and read only its own slice instead of
    reaching into the live store mid-reduce.
    """

    depth: int
    is_on_notification: bool
    is_display_blanked: bool


class KeypadState(Immutable):
    is_consumed: bool = False
    depth: int = 0
    is_on_notification: bool = False
    is_display_blanked: bool = False
