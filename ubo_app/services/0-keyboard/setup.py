# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from kivy.core.window import Keyboard, Window, WindowBase

from ubo_app.store.keypad import (
    Key,
    KeypadActionPayload,
    KeypadKeyPressAction,
)
from ubo_app.store.sound import (
    SoundDevice,
    SoundToggleMuteStatusAction,
    SoundToggleMuteStatusActionPayload,
)

if TYPE_CHECKING:
    Modifier = Literal['ctrl', 'alt', 'meta', 'shift']


def on_keyboard(
    _: WindowBase,
    key: int,
    _scancode: int,
    _codepoint: str,
    modifier: list[Modifier],
) -> None:
    """Handle keyboard events."""
    from ubo_app.store import dispatch

    if modifier == []:
        if key == Keyboard.keycodes['up']:
            dispatch(KeypadKeyPressAction(payload=KeypadActionPayload(key=Key.UP)))
        elif key == Keyboard.keycodes['down']:
            dispatch(KeypadKeyPressAction(payload=KeypadActionPayload(key=Key.DOWN)))
        elif key == Keyboard.keycodes['1']:
            dispatch(KeypadKeyPressAction(payload=KeypadActionPayload(key=Key.L1)))
        elif key == Keyboard.keycodes['2']:
            dispatch(KeypadKeyPressAction(payload=KeypadActionPayload(key=Key.L2)))
        elif key == Keyboard.keycodes['3']:
            dispatch(KeypadKeyPressAction(payload=KeypadActionPayload(key=Key.L3)))
        elif key == Keyboard.keycodes['left']:
            dispatch(KeypadKeyPressAction(payload=KeypadActionPayload(key=Key.BACK)))
        elif key == Keyboard.keycodes['m']:
            from ubo_app.store import dispatch

            dispatch(
                SoundToggleMuteStatusAction(
                    payload=SoundToggleMuteStatusActionPayload(
                        device=SoundDevice.INPUT,
                    ),
                ),
            )


Window.bind(on_keyboard=on_keyboard)
