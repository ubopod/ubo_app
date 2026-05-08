"""Keyboard handling for the GUI client.

Maps desktop keyboard keys to keypad actions and dispatches them via gRPC.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Literal

from kivy.core.window import Keyboard, Window, WindowBase

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_gui.menu.menu_widget import MenuWidget

    from ubo_gui_client.client import GUIClient

logger = logging.getLogger(__name__)

Modifier = Literal['ctrl', 'alt', 'meta', 'shift']

# Key code constants (from Kivy Keyboard.keycodes)
_UP = Keyboard.keycodes['up']
_DOWN = Keyboard.keycodes['down']
_LEFT = Keyboard.keycodes['left']
_ESCAPE = Keyboard.keycodes['escape']
_BACKSPACE = Keyboard.keycodes['backspace']
_K = Keyboard.keycodes['k']
_J = Keyboard.keycodes['j']
_H = Keyboard.keycodes['h']
_V = Keyboard.keycodes['v']
_M = Keyboard.keycodes['m']
_1 = Keyboard.keycodes['1']
_2 = Keyboard.keycodes['2']
_3 = Keyboard.keycodes['3']


def _build_key_maps() -> tuple[dict, dict, dict]:
    """Build keyboard-to-action maps."""
    from ubo_bindings.ubo.v1 import (
        Action,
        AudioDevice,
        AudioToggleMuteStatusAction,
        Key,
        KeypadKeyPressAction,
        KeypadKeyReleaseAction,
    )

    def _press(key: Key, *extra_keys: Key) -> Action:
        return Action(
            keypad_key_press_action=KeypadKeyPressAction(
                key=key,
                pressed_keys=[key, *extra_keys],
            ),
        )

    def _release(key: Key, *extra_keys: Key) -> Action:
        return Action(
            keypad_key_release_action=KeypadKeyReleaseAction(
                key=key,
                pressed_keys=list(extra_keys),
            ),
        )

    no_mod_map: dict[int, Action] = {
        _UP: _press(Key.UP),
        _K: _press(Key.UP),
        _DOWN: _press(Key.DOWN),
        _J: _press(Key.DOWN),
        _1: _press(Key.L1),
        _2: _press(Key.L2),
        _3: _press(Key.L3),
        _LEFT: _release(Key.BACK),
        _ESCAPE: _release(Key.BACK),
        _H: _release(Key.BACK),
        _BACKSPACE: _release(Key.HOME),
        _M: Action(
            audio_toggle_mute_status_action=AudioToggleMuteStatusAction(
                device=AudioDevice.INPUT,
            ),
        ),
    }

    ctrl_map: dict[int, Action] = {
        _UP: _press(Key.UP, Key.BACK),
        _K: _press(Key.UP, Key.BACK),
        _DOWN: _press(Key.DOWN, Key.BACK),
        _J: _press(Key.DOWN, Key.BACK),
        _1: _press(Key.L1, Key.BACK),
        _2: _press(Key.L2, Key.BACK),
        _3: _press(Key.L3, Key.BACK),
        _BACKSPACE: _press(Key.HOME, Key.BACK),
    }

    shift_map: dict[int, Action] = {
        _UP: _press(Key.UP, Key.HOME),
        _K: _press(Key.UP, Key.HOME),
        _DOWN: _press(Key.DOWN, Key.HOME),
        _J: _press(Key.DOWN, Key.HOME),
        _1: _press(Key.L1, Key.HOME),
        _2: _press(Key.L2, Key.HOME),
        _3: _press(Key.L3, Key.HOME),
        _LEFT: _press(Key.BACK, Key.HOME),
        _ESCAPE: _press(Key.BACK, Key.HOME),
        _H: _press(Key.BACK, Key.HOME),
    }

    return no_mod_map, ctrl_map, shift_map


def setup_keyboard(  # noqa: C901, PLR0915
    client: GUIClient,
    menu_widget: MenuWidget | None = None,
) -> list[Callable[[], None]]:
    """Set up keyboard bindings that dispatch actions via gRPC.

    When *menu_widget* is provided, L1/L2/L3 presses also call
    ``menu_widget.select(index)`` so that local Kivy actions fire
    (e.g. opening the notification-info page).

    Returns a list of cleanup callables.
    """
    from ubo_bindings.ubo.v1 import (
        Action,
        AssistantStartListeningAction,
        AssistantStopListeningAction,
        AssistantStopReasonUnion,
        AssistantTriggerSourceUnion,
        DesktopTriggerSource,
        UserStopReason,
    )

    no_mod_map, ctrl_map, shift_map = _build_key_maps()
    v_key_held = False

    # Map key codes to select() indices for L1/L2/L3
    _select_keys: dict[int, int] = {_1: 0, _2: 1, _3: 2}
    _back_keys: set[int] = {_LEFT, _ESCAPE, _H}
    _scroll_up_keys: set[int] = {_UP, _K}
    _scroll_down_keys: set[int] = {_DOWN, _J}

    def _is_local_only_page() -> bool:
        """Check if the current Kivy application is a local-only page.

        Local-only pages (e.g. NotificationInfo) exist only on the Kivy
        stack and have no counterpart in the core's Redux stack.  BACK
        must be handled locally for these without dispatching to the core.
        """
        if menu_widget is None:
            return False
        current_app = menu_widget.current_application
        if current_app is None:
            return False
        from ubo_gui_client.widgets.notification_info import NotificationInfo

        return isinstance(current_app, NotificationInfo)

    def _should_skip_select_dispatch(key: int) -> bool:
        """Check if L1/L2/L3 dispatch should be skipped.

        Returns True when the current application has no selectable item
        at the pressed button index, preventing useless events that can
        trigger blocking operations in the core.
        """
        if menu_widget is None or menu_widget.current_application is None:
            return False
        item = menu_widget.current_application.get_item(_select_keys[key])
        if item is None:
            logger.debug(
                '[Keyboard] Skipping dispatch for L%d — no item',
                _select_keys[key] + 1,
            )
            return True
        return False

    def _try_local_select_action(key: int) -> None:
        """Invoke the local action for L1/L2/L3 on the current app.

        Fires GUI-only actions (e.g. notification info page) directly
        instead of going through the full Kivy selection pipeline.
        """
        if menu_widget is None:
            return
        current_app = menu_widget.current_application
        if current_app is None:
            return
        item = current_app.get_item(_select_keys[key])
        if item is not None and hasattr(item, 'action'):
            action = getattr(item, 'action', None)
            if callable(action):
                logger.info(
                    '[Keyboard] Local action for L%d on %s',
                    _select_keys[key] + 1,
                    type(current_app).__name__,
                )
                action()

    def on_keyboard(  # noqa: C901
        window: WindowBase,
        key: int,
        scancode: int,
        codepoint: str,
        modifier: list[Modifier],
    ) -> None:
        """Handle keyboard events."""
        _ = window, scancode, codepoint

        logger.debug(
            '[Keyboard] key=%d, codepoint=%r, modifier=%s',
            key,
            codepoint,
            modifier,
        )

        # Intercept BACK when a local-only page (e.g. NotificationInfo)
        # is on the Kivy stack — pop it locally, don't send to core.
        if (
            modifier == []
            and key in _back_keys
            and menu_widget is not None
            and _is_local_only_page()
        ):
            logger.info('[Keyboard] BACK on local-only page — popping locally')
            menu_widget.go_back()
            return

        action = None
        if modifier == [] and key in no_mod_map:
            action = no_mod_map[key]
        elif modifier == ['ctrl'] and key in ctrl_map:
            action = ctrl_map[key]
        elif modifier == ['shift'] and key in shift_map:
            action = shift_map[key]

        # Skip L1/L2/L3 dispatch when there's no selectable item
        if (
            action
            and modifier == []
            and key in _select_keys
            and _should_skip_select_dispatch(key)
        ):
            action = None

        if action:
            logger.info(
                '[Keyboard] Dispatching action for key=%d mod=%s',
                key,
                modifier,
            )
            client.dispatch_raw(action)

        # For L1/L2/L3, invoke local actions on LOCAL-ONLY pages only.
        # Non-local application pages get their actions via the
        # MenuChooseByIndexEvent subscription in view_renderer.py.
        if modifier == [] and key in _select_keys and _is_local_only_page():
            _try_local_select_action(key)

        # For UP/DOWN, scroll LOCAL-ONLY application pages only.
        # Non-local application pages get scrolled via the
        # ApplicationScrollEvent subscription in view_renderer.py.
        if modifier == [] and menu_widget is not None and _is_local_only_page():
            if key in _scroll_up_keys:
                menu_widget.go_up()
            elif key in _scroll_down_keys:
                menu_widget.go_down()

    def on_key_down(
        window: WindowBase,
        key: int,
        scancode: int,
        codepoint: str,
        modifier: list[Modifier],
    ) -> None:
        """Handle key down events."""
        nonlocal v_key_held

        _ = window, scancode, codepoint
        if modifier == [] and key == _V and not v_key_held:
            v_key_held = True
            client.dispatch_raw(
                Action(
                    assistant_start_listening_action=AssistantStartListeningAction(
                        source=AssistantTriggerSourceUnion(
                            desktop_trigger_source=DesktopTriggerSource(),
                        ),
                    ),
                ),
            )

    def on_key_up(
        window: WindowBase,
        key: int,
        scancode: int,
    ) -> None:
        """Handle key up events."""
        nonlocal v_key_held

        _ = window, scancode
        if key == _V and v_key_held:
            v_key_held = False
            client.dispatch_raw(
                Action(
                    assistant_stop_listening_action=AssistantStopListeningAction(
                        reason=AssistantStopReasonUnion(
                            user_stop_reason=UserStopReason(
                                source=AssistantTriggerSourceUnion(
                                    desktop_trigger_source=DesktopTriggerSource(),
                                ),
                            ),
                        ),
                    ),
                ),
            )

    Window.bind(on_keyboard=on_keyboard)
    Window.bind(on_key_down=on_key_down)
    Window.bind(on_key_up=on_key_up)

    return [
        functools.partial(Window.unbind, on_keyboard=on_keyboard),
        functools.partial(Window.unbind, on_key_down=on_key_down),
        functools.partial(Window.unbind, on_key_up=on_key_up),
    ]
