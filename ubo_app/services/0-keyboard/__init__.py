# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from kivy.core.window import Keyboard, Window, WindowBase

from ubo_app.store.keypad import Key, dispatch_key

if TYPE_CHECKING:
    Modifier = Literal['ctrl', 'alt', 'meta', 'shift']

ubo_service_name = 'keypad'
ubo_service_description = 'Keypad device'


def on_keyboard(
    _: WindowBase,
    key: int,
    _scancode: int,
    _codepoint: str,
    modifier: list[Modifier],
) -> None:
    """Handle keyboard events."""
    if modifier == []:
        if key == Keyboard.keycodes['up']:
            dispatch_key('KEYPAD_KEY_PRESS', Key.UP)
        elif key == Keyboard.keycodes['down']:
            dispatch_key('KEYPAD_KEY_PRESS', Key.DOWN)
        elif key == Keyboard.keycodes['1']:
            dispatch_key('KEYPAD_KEY_PRESS', Key.L1)
        elif key == Keyboard.keycodes['2']:
            dispatch_key('KEYPAD_KEY_PRESS', Key.L2)
        elif key == Keyboard.keycodes['3']:
            dispatch_key('KEYPAD_KEY_PRESS', Key.L3)
        elif key == Keyboard.keycodes['left']:
            dispatch_key('KEYPAD_KEY_PRESS', Key.BACK)


Window.bind(on_keyboard=on_keyboard)
