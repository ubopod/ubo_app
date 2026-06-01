"""Unit tests for the (now pure) keypad reducer.

The keypad reducer reads cross-slice UI context (menu depth, notification/display
state) only from its own ``KeypadState`` slice — mirrored there by the keypad service's
autorun (see ``ubo_app/services/000-keypad/setup.py``). These tests exercise that pure
decision logic directly, constructing ``KeypadState`` with the mirrored fields and
asserting the emitted actions/events. No store, autorun, or hardware is involved.

The reducer lives in a hyphenated service directory, so it is loaded by file path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from redux import CompleteReducerResult

from ubo_app.store.core.types import (
    MenuChooseByIndexEvent,
    MenuGoBackAction,
    MenuScrollAction,
)
from ubo_app.store.services.audio import AudioChangeVolumeAction
from ubo_app.store.services.display import DisplayUnblankAction
from ubo_app.store.services.keypad import (
    Key,
    KeypadKeyPressAction,
    KeypadKeyReleaseAction,
    KeypadReportContextAction,
    KeypadState,
)

_REDUCER_PATH = (
    Path(__file__).resolve().parents[2]
    / 'ubo_app'
    / 'services'
    / '000-keypad'
    / 'reducer.py'
)
_spec = importlib.util.spec_from_file_location(
    'keypad_reducer_under_test',
    _REDUCER_PATH,
)
assert _spec is not None
assert _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
reducer = _module.reducer


def _press(key: Key) -> KeypadKeyPressAction:
    """Build a single-key press action."""
    return KeypadKeyPressAction(key=key, pressed_keys=(key,))


class TestContextMirror:
    """The reducer mirrors ``KeypadReportContextAction`` into its own slice."""

    def test_report_context_updates_state(self) -> None:
        """Context action updates depth/notification/display mirror fields."""
        result = reducer(
            KeypadState(),
            KeypadReportContextAction(
                depth=3,
                is_on_notification=True,
                is_display_blanked=True,
            ),
        )
        assert isinstance(result, KeypadState)
        assert result.depth == 3
        assert result.is_on_notification is True
        assert result.is_display_blanked is True


class TestDepthDependentBehaviour:
    """Behaviour driven by the mirrored ``depth`` field."""

    def test_up_at_depth_one_changes_volume(self) -> None:
        """UP on the home screen (depth 1) changes volume."""
        result = reducer(KeypadState(depth=1), _press(Key.UP))
        assert isinstance(result, CompleteReducerResult)
        assert any(
            isinstance(action, AudioChangeVolumeAction)
            for action in result.actions or ()
        )

    def test_up_at_depth_two_scrolls(self) -> None:
        """UP deeper in the menu (depth > 1) scrolls instead of changing volume."""
        result = reducer(KeypadState(depth=2), _press(Key.UP))
        assert isinstance(result, CompleteReducerResult)
        assert any(
            isinstance(action, MenuScrollAction) for action in result.actions or ()
        )


class TestScreenWake:
    """A key press on a blanked screen wakes it and is consumed."""

    def test_keypress_wakes_blanked_screen(self) -> None:
        """When blanked, a press emits DisplayUnblankAction and is consumed."""
        result = reducer(KeypadState(is_display_blanked=True), _press(Key.L1))
        assert isinstance(result, CompleteReducerResult)
        assert result.actions == [DisplayUnblankAction()]
        assert isinstance(result.state, KeypadState)
        assert result.state.is_consumed is True

    def test_keypress_when_not_blanked_does_not_wake(self) -> None:
        """When not blanked, a press does not emit DisplayUnblankAction."""
        result = reducer(KeypadState(is_display_blanked=False, depth=2), _press(Key.UP))
        assert isinstance(result, CompleteReducerResult)
        assert not any(
            isinstance(action, DisplayUnblankAction) for action in result.actions or ()
        )


class TestChooseByIndex:
    """L1/L2/L3 emit MenuChooseByIndexEvent; the handler gates the index."""

    def test_l1_chooses_index_zero(self) -> None:
        """L1 emits MenuChooseByIndexEvent(index=0) regardless of context."""
        result = reducer(KeypadState(is_on_notification=True), _press(Key.L1))
        assert isinstance(result, CompleteReducerResult)
        assert any(
            isinstance(event, MenuChooseByIndexEvent) and event.index == 0
            for event in result.events or ()
        )

    def test_l3_chooses_index_two(self) -> None:
        """L3 emits MenuChooseByIndexEvent(index=2)."""
        result = reducer(KeypadState(), _press(Key.L3))
        assert isinstance(result, CompleteReducerResult)
        assert any(
            isinstance(event, MenuChooseByIndexEvent) and event.index == 2
            for event in result.events or ()
        )


class TestNavigation:
    """Plain navigation actions independent of mirrored context."""

    def test_back_release_goes_back(self) -> None:
        """Releasing BACK alone emits MenuGoBackAction."""
        result = reducer(
            KeypadState(),
            KeypadKeyReleaseAction(key=Key.BACK, pressed_keys=()),
        )
        assert isinstance(result, CompleteReducerResult)
        assert any(
            isinstance(action, MenuGoBackAction) for action in result.actions or ()
        )
