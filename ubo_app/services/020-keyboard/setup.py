# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from kivy.core.window import Keyboard, Window, WindowBase
from redux import FinishEvent

from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioDevice, AudioToggleMuteStatusAction
from ubo_app.store.services.keypad import (
    Key,
    KeypadKeyPressAction,
    KeypadKeyReleaseAction,
)

if TYPE_CHECKING:
    Modifier = Literal['ctrl', 'alt', 'meta', 'shift']

KEY_MAP = {
    'no_modifier': {
        Keyboard.keycodes['up']: KeypadKeyPressAction(
            key=Key.UP,
            pressed_keys={Key.UP},
        ),
        Keyboard.keycodes['k']: KeypadKeyPressAction(key=Key.UP, pressed_keys={Key.UP}),
        Keyboard.keycodes['down']: KeypadKeyPressAction(
            key=Key.DOWN,
            pressed_keys={Key.DOWN},
        ),
        Keyboard.keycodes['j']: KeypadKeyPressAction(
            key=Key.DOWN,
            pressed_keys={Key.DOWN},
        ),
        Keyboard.keycodes['1']: KeypadKeyPressAction(key=Key.L1, pressed_keys={Key.L1}),
        Keyboard.keycodes['2']: KeypadKeyPressAction(key=Key.L2, pressed_keys={Key.L2}),
        Keyboard.keycodes['3']: KeypadKeyPressAction(key=Key.L3, pressed_keys={Key.L3}),
        Keyboard.keycodes['left']: KeypadKeyReleaseAction(
            key=Key.BACK,
            pressed_keys=set(),
        ),
        Keyboard.keycodes['escape']: KeypadKeyReleaseAction(
            key=Key.BACK,
            pressed_keys=set(),
        ),
        Keyboard.keycodes['h']: KeypadKeyReleaseAction(
            key=Key.BACK,
            pressed_keys=set(),
        ),
        Keyboard.keycodes['backspace']: KeypadKeyReleaseAction(
            key=Key.HOME,
            pressed_keys=set(),
        ),
        Keyboard.keycodes['m']: AudioToggleMuteStatusAction(device=AudioDevice.INPUT),
        Keyboard.keycodes['p']: KeypadKeyPressAction(
            key=Key.L1,
            pressed_keys={Key.HOME, Key.L1},
        ),
        Keyboard.keycodes['s']: KeypadKeyPressAction(
            key=Key.L2,
            pressed_keys={Key.HOME, Key.L2},
        ),
        Keyboard.keycodes['r']: KeypadKeyPressAction(
            key=Key.L3,
            pressed_keys={Key.HOME, Key.L3},
        ),
        Keyboard.keycodes['q']: KeypadKeyPressAction(
            key=Key.BACK,
            pressed_keys={Key.HOME, Key.BACK},
        ),
    },
    'ctrl': {
        Keyboard.keycodes['r']: KeypadKeyPressAction(
            key=Key.L3,
            pressed_keys={Key.BACK, Key.L3},
        ),
    },
}


def on_keyboard(
    window: WindowBase,
    key: int,
    scancode: int,
    codepoint: str,
    modifier: list[Modifier],
) -> None:
    """Handle keyboard events."""
    _ = window, scancode, codepoint
    from ubo_app.store.main import store

    if modifier == [] and key in KEY_MAP['no_modifier']:
        store.dispatch(KEY_MAP['no_modifier'][key])
    elif modifier == ['ctrl'] and key in KEY_MAP['ctrl']:
        store.dispatch(KEY_MAP['ctrl'][key])


def init_service() -> None:
    Window.bind(on_keyboard=on_keyboard)

    store.subscribe_event(FinishEvent, lambda: Window.unbind(on_keyboard=on_keyboard))
