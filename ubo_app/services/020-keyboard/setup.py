# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from kivy.core.window import Keyboard, Window, WindowBase
from redux import FinishAction, FinishEvent

from ubo_app.store.main import ScreenshotEvent, SnapshotEvent, subscribe_event
from ubo_app.store.services.keypad import Key, KeypadKeyPressAction
from ubo_app.store.services.sound import SoundDevice, SoundToggleMuteStatusAction

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
    from ubo_app.store.main import dispatch

    if modifier == []:
        if key in (Keyboard.keycodes['up'], Keyboard.keycodes['k']):
            dispatch(KeypadKeyPressAction(key=Key.UP))
        elif key in (Keyboard.keycodes['down'], Keyboard.keycodes['j']):
            dispatch(KeypadKeyPressAction(key=Key.DOWN))
        elif key == Keyboard.keycodes['1']:
            dispatch(KeypadKeyPressAction(key=Key.L1))
        elif key == Keyboard.keycodes['2']:
            dispatch(KeypadKeyPressAction(key=Key.L2))
        elif key == Keyboard.keycodes['3']:
            dispatch(KeypadKeyPressAction(key=Key.L3))
        elif key in (
            Keyboard.keycodes['left'],
            Keyboard.keycodes['escape'],
            Keyboard.keycodes['h'],
        ):
            dispatch(KeypadKeyPressAction(key=Key.BACK))
        elif key == Keyboard.keycodes['backspace']:
            dispatch(KeypadKeyPressAction(key=Key.HOME))
        elif key == Keyboard.keycodes['m']:
            from ubo_app.store.main import dispatch

            dispatch(
                SoundToggleMuteStatusAction(
                    device=SoundDevice.INPUT,
                ),
            )
        elif key == Keyboard.keycodes['p']:
            dispatch(ScreenshotEvent())
        elif key == Keyboard.keycodes['s']:
            dispatch(SnapshotEvent())
        elif key == Keyboard.keycodes['q']:
            dispatch(FinishAction())


def init_service() -> None:
    Window.bind(on_keyboard=on_keyboard)

    subscribe_event(FinishEvent, lambda: Window.unbind(on_keyboard=on_keyboard))
