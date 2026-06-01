"""Map keypad key names from the C renderer to gRPC keypad Actions.

The C SDL backend emits "UP"/"DOWN"/"L1"/"L2"/"L3"/"BACK"/"HOME"; on the device
the physical keypad is read by a core service instead. Mirrors the Kivy client's
keyboard.py: UP/DOWN/L1-3 are press actions, BACK/HOME are release actions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_bindings.ubo.v1 import Action


def build_action(key: str) -> Action | None:
    """Return the gRPC Action for a key-down of `key`, or None."""
    from ubo_bindings.ubo.v1 import (
        Action,
        Key,
        KeypadKeyPressAction,
        KeypadKeyReleaseAction,
    )

    press = {
        'UP': Key.UP,
        'DOWN': Key.DOWN,
        'L1': Key.L1,
        'L2': Key.L2,
        'L3': Key.L3,
    }
    release = {'BACK': Key.BACK, 'HOME': Key.HOME}

    if key in press:
        k = press[key]
        return Action(
            keypad_key_press_action=KeypadKeyPressAction(key=k, pressed_keys=[k]),
        )
    if key in release:
        k = release[key]
        return Action(
            keypad_key_release_action=KeypadKeyReleaseAction(key=k, pressed_keys=[]),
        )
    return None
