# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from kivy.core.window import Keyboard, Window, WindowBase
from redux import FinishEvent

from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioDevice, AudioToggleMuteStatusAction
from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

if TYPE_CHECKING:
    Modifier = Literal['ctrl', 'alt', 'meta', 'shift']


def on_keyboard(  # noqa: C901
    window: WindowBase,
    key: int,
    scancode: int,
    codepoint: str,
    modifier: list[Modifier],
) -> None:
    """Handle keyboard events."""
    _ = window, scancode, codepoint
    from ubo_app.store.main import store

    if modifier == []:
        if key in (Keyboard.keycodes['up'], Keyboard.keycodes['k']):
            store.dispatch(KeypadKeyPressAction(key=Key.UP, pressed_keys=set()))
        elif key in (Keyboard.keycodes['down'], Keyboard.keycodes['j']):
            store.dispatch(KeypadKeyPressAction(key=Key.DOWN, pressed_keys=set()))
        elif key == Keyboard.keycodes['1']:
            store.dispatch(KeypadKeyPressAction(key=Key.L1, pressed_keys=set()))
        elif key == Keyboard.keycodes['2']:
            store.dispatch(KeypadKeyPressAction(key=Key.L2, pressed_keys=set()))
        elif key == Keyboard.keycodes['3']:
            store.dispatch(KeypadKeyPressAction(key=Key.L3, pressed_keys=set()))
        elif key in (
            Keyboard.keycodes['left'],
            Keyboard.keycodes['escape'],
            Keyboard.keycodes['h'],
        ):
            store.dispatch(KeypadKeyPressAction(key=Key.BACK, pressed_keys=set()))
        elif key == Keyboard.keycodes['backspace']:
            store.dispatch(KeypadKeyPressAction(key=Key.HOME, pressed_keys=set()))
        elif key == Keyboard.keycodes['m']:
            from ubo_app.store.main import store

            store.dispatch(
                AudioToggleMuteStatusAction(
                    device=AudioDevice.INPUT,
                ),
            )
        elif key == Keyboard.keycodes['p']:
            store.dispatch(
                KeypadKeyPressAction(key=Key.L1, pressed_keys={Key.HOME, Key.L1}),
            )
        elif key == Keyboard.keycodes['s']:
            store.dispatch(
                KeypadKeyPressAction(key=Key.L2, pressed_keys={Key.HOME, Key.L2}),
            )
        elif key == Keyboard.keycodes['q']:
            store.dispatch(
                KeypadKeyPressAction(key=Key.BACK, pressed_keys={Key.HOME, Key.BACK}),
            )


def init_service() -> None:
    Window.bind(on_keyboard=on_keyboard)

    store.subscribe_event(FinishEvent, lambda: Window.unbind(on_keyboard=on_keyboard))
