# ruff: noqa: D100, D103
from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Literal

from kivy.core.window import Keyboard, Window, WindowBase

from ubo_app.store.services.assistant import (
    AssistantStartListeningAction,
    AssistantStopListeningAction,
)
from ubo_app.store.services.audio import AudioDevice, AudioToggleMuteStatusAction
from ubo_app.store.services.keypad import (
    Key,
    KeypadKeyPressAction,
    KeypadKeyReleaseAction,
)

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions

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
    },
    'ctrl': {
        Keyboard.keycodes['up']: KeypadKeyPressAction(
            key=Key.UP,
            pressed_keys={Key.BACK, Key.UP},
        ),
        Keyboard.keycodes['k']: KeypadKeyPressAction(
            key=Key.UP,
            pressed_keys={Key.BACK, Key.UP},
        ),
        Keyboard.keycodes['down']: KeypadKeyPressAction(
            key=Key.DOWN,
            pressed_keys={Key.BACK, Key.DOWN},
        ),
        Keyboard.keycodes['j']: KeypadKeyPressAction(
            key=Key.DOWN,
            pressed_keys={Key.BACK, Key.DOWN},
        ),
        Keyboard.keycodes['1']: KeypadKeyPressAction(
            key=Key.L1,
            pressed_keys={Key.BACK, Key.L1},
        ),
        Keyboard.keycodes['2']: KeypadKeyPressAction(
            key=Key.L2,
            pressed_keys={Key.BACK, Key.L2},
        ),
        Keyboard.keycodes['3']: KeypadKeyPressAction(
            key=Key.L3,
            pressed_keys={Key.BACK, Key.L3},
        ),
        Keyboard.keycodes['backspace']: KeypadKeyPressAction(
            key=Key.HOME,
            pressed_keys={Key.BACK, Key.HOME},
        ),
    },
    'shift': {
        Keyboard.keycodes['up']: KeypadKeyPressAction(
            key=Key.UP,
            pressed_keys={Key.HOME, Key.UP},
        ),
        Keyboard.keycodes['k']: KeypadKeyPressAction(
            key=Key.UP,
            pressed_keys={Key.HOME, Key.UP},
        ),
        Keyboard.keycodes['down']: KeypadKeyPressAction(
            key=Key.DOWN,
            pressed_keys={Key.HOME, Key.DOWN},
        ),
        Keyboard.keycodes['j']: KeypadKeyPressAction(
            key=Key.DOWN,
            pressed_keys={Key.HOME, Key.DOWN},
        ),
        Keyboard.keycodes['1']: KeypadKeyPressAction(
            key=Key.L1,
            pressed_keys={Key.HOME, Key.L1},
        ),
        Keyboard.keycodes['2']: KeypadKeyPressAction(
            key=Key.L2,
            pressed_keys={Key.HOME, Key.L2},
        ),
        Keyboard.keycodes['3']: KeypadKeyPressAction(
            key=Key.L3,
            pressed_keys={Key.HOME, Key.L3},
        ),
        Keyboard.keycodes['left']: KeypadKeyPressAction(
            key=Key.BACK,
            pressed_keys={Key.HOME, Key.BACK},
        ),
        Keyboard.keycodes['escape']: KeypadKeyPressAction(
            key=Key.BACK,
            pressed_keys={Key.HOME, Key.BACK},
        ),
        Keyboard.keycodes['h']: KeypadKeyPressAction(
            key=Key.BACK,
            pressed_keys={Key.HOME, Key.BACK},
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
    elif modifier == ['shift'] and key in KEY_MAP['shift']:
        store.dispatch(KEY_MAP['shift'][key])


def on_key_down(
    window: WindowBase,
    key: int,
    scancode: int,
    codepoint: str,
    modifier: list[Modifier],
) -> None:
    """Handle key down events."""
    _ = window, scancode, codepoint
    from ubo_app.store.main import store

    if modifier == [] and key == Keyboard.keycodes['v']:
        store.dispatch(AssistantStartListeningAction())


def on_key_up(
    window: WindowBase,
    key: int,
    scancode: int,
) -> None:
    """Handle key up events."""
    _ = window, scancode
    from ubo_app.store.main import store

    if key == Keyboard.keycodes['v']:
        store.dispatch(AssistantStopListeningAction())


def init_service() -> Subscriptions:
    Window.bind(on_keyboard=on_keyboard)
    Window.bind(on_key_down=on_key_down)
    Window.bind(on_key_up=on_key_up)

    return [
        functools.partial(Window.unbind, on_keyboard=on_keyboard),
        functools.partial(Window.unbind, on_key_down=on_key_down),
        functools.partial(Window.unbind, on_key_up=on_key_up),
    ]
