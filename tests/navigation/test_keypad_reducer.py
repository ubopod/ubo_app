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

import pytest
from redux import (
    CompleteReducerResult,
    FinishEvent,
    InitAction,
    InitializationActionError,
)

from ubo_app.store.core.types import (
    MenuChooseByIndexEvent,
    MenuGoBackAction,
    MenuGoHomeAction,
    MenuScrollAction,
    ReplayRecordedSequenceAction,
    SnapshotEvent,
    TakeScreenshotAction,
    ToggleRecordingAction,
)
from ubo_app.store.services.assistant import (
    AssistantStartListeningAction,
    AssistantStopListeningAction,
)
from ubo_app.store.services.audio import (
    AudioChangeVolumeAction,
    AudioPlayRecordingAction,
    AudioToggleRecordingAction,
)
from ubo_app.store.services.display import DisplayUnblankAction
from ubo_app.store.services.keypad import (
    Key,
    KeypadKeyHoldAction,
    KeypadKeyPressAction,
    KeypadKeyReleaseAction,
    KeypadKeyUnholdAction,
    KeypadReportContextAction,
    KeypadState,
)
from ubo_app.store.services.notifications import NotificationsAddAction

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
                is_on_chat=True,
                is_on_application=True,
                is_display_blanked=True,
            ),
        )
        assert isinstance(result, KeypadState)
        assert result.depth == 3
        assert result.is_on_notification is True
        assert result.is_on_chat is True
        assert result.is_on_application is True
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

    def test_up_on_application_view_scrolls_not_volume(self) -> None:
        """UP on a render/application view (e.g. image viewer) at depth 1 scrolls.

        The view owns up/down for pan/zoom, so the home-screen volume shortcut
        must not fire even though depth is 1.
        """
        result = reducer(
            KeypadState(depth=1, is_on_application=True),
            _press(Key.UP),
        )
        assert isinstance(result, CompleteReducerResult)
        actions = result.actions or ()
        assert not any(
            isinstance(action, AudioChangeVolumeAction) for action in actions
        )
        assert any(isinstance(action, MenuScrollAction) for action in actions)


class TestScreenWake:
    """A key press on a blanked screen wakes it and is consumed."""

    def test_keypress_wakes_blanked_screen(self) -> None:
        """When blanked, a press emits DisplayUnblankAction and is consumed."""
        result = reducer(KeypadState(is_display_blanked=True), _press(Key.L1))
        assert isinstance(result, CompleteReducerResult)
        # ``DisplayUnblankAction`` carries a non-deterministic ``timestamp`` field,
        # so assert on the action type rather than equality with a fresh instance.
        assert result.actions is not None
        assert len(result.actions) == 1
        assert isinstance(result.actions[0], DisplayUnblankAction)
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


def _emitted(result: object) -> list[object]:
    """Flatten a reducer result's actions and events for type assertions."""
    actions: list[object] = list(getattr(result, 'actions', None) or ())
    events: list[object] = list(getattr(result, 'events', None) or ())
    return actions + events


class TestInitialization:
    """The None-state initialization contract."""

    def test_init_action_builds_default_state(self) -> None:
        """A None state plus InitAction yields a fresh default state."""
        assert isinstance(reducer(None, InitAction()), KeypadState)

    def test_none_state_without_init_raises(self) -> None:
        """Any non-init action against a None state is an initialization error."""
        with pytest.raises(InitializationActionError):
            reducer(None, _press(Key.L1))


class TestHomeListening:
    """HOME drives the assistant listening lifecycle."""

    def test_home_press_at_depth_one_starts_listening(self) -> None:
        """HOME on the home screen starts assistant listening (press mode)."""
        result = reducer(KeypadState(depth=1), _press(Key.HOME))
        assert any(
            isinstance(action, AssistantStartListeningAction)
            for action in _emitted(result)
        )

    def test_home_release_at_depth_one_stops_listening_without_going_home(
        self,
    ) -> None:
        """Releasing HOME on the home screen stops listening but does not navigate."""
        result = reducer(
            KeypadState(depth=1),
            KeypadKeyReleaseAction(key=Key.HOME, pressed_keys=()),
        )
        emitted = _emitted(result)
        assert any(isinstance(a, AssistantStopListeningAction) for a in emitted)
        assert not any(isinstance(a, MenuGoHomeAction) for a in emitted)

    def test_home_release_deep_stops_listening_and_goes_home(self) -> None:
        """Releasing HOME deeper in the menu stops listening and navigates home."""
        result = reducer(
            KeypadState(depth=3),
            KeypadKeyReleaseAction(key=Key.HOME, pressed_keys=()),
        )
        emitted = _emitted(result)
        assert any(isinstance(a, AssistantStopListeningAction) for a in emitted)
        assert any(isinstance(a, MenuGoHomeAction) for a in emitted)

    def test_home_hold_deep_starts_hold_listening_and_consumes(self) -> None:
        """Holding HOME deeper in the menu starts hold-listening and consumes it."""
        result = reducer(
            KeypadState(depth=2),
            KeypadKeyHoldAction(
                key=Key.HOME,
                pressed_keys=(Key.HOME,),
                held_keys=(Key.HOME,),
            ),
        )
        assert any(
            isinstance(a, AssistantStartListeningAction) for a in _emitted(result)
        )
        assert result.state.is_consumed is True

    def test_home_unhold_stops_hold_listening_and_consumes(self) -> None:
        """Unholding HOME stops hold-listening and consumes it."""
        result = reducer(
            KeypadState(depth=2, is_consumed=True),
            KeypadKeyUnholdAction(key=Key.HOME, pressed_keys=(Key.HOME,)),
        )
        assert any(
            isinstance(a, AssistantStopListeningAction) for a in _emitted(result)
        )
        assert result.state.is_consumed is True


class TestChooseByIndexAndScroll:
    """Single-key L2 and DOWN behaviours not covered elsewhere."""

    def test_l2_chooses_index_one(self) -> None:
        """L2 emits MenuChooseByIndexEvent(index=1)."""
        result = reducer(KeypadState(), _press(Key.L2))
        assert any(
            isinstance(e, MenuChooseByIndexEvent) and e.index == 1
            for e in _emitted(result)
        )

    def test_down_at_depth_one_changes_volume(self) -> None:
        """DOWN on the home screen lowers the volume."""
        result = reducer(KeypadState(depth=1), _press(Key.DOWN))
        volume_actions = [
            a for a in _emitted(result) if isinstance(a, AudioChangeVolumeAction)
        ]
        assert volume_actions
        assert volume_actions[0].amount < 0

    def test_down_at_depth_two_scrolls_down(self) -> None:
        """DOWN deeper in the menu scrolls instead of changing volume."""
        result = reducer(KeypadState(depth=2), _press(Key.DOWN))
        scrolls = [a for a in _emitted(result) if isinstance(a, MenuScrollAction)]
        assert scrolls
        assert scrolls[0].direction.value == 'down'


_COMBOS = [
    pytest.param(Key.L1, (Key.HOME, Key.L1), TakeScreenshotAction, id='home+l1'),
    pytest.param(Key.L2, (Key.HOME, Key.L2), SnapshotEvent, id='home+l2'),
    pytest.param(Key.L3, (Key.HOME, Key.L3), ToggleRecordingAction, id='home+l3'),
    pytest.param(Key.L1, (Key.BACK, Key.L1), AudioToggleRecordingAction, id='back+l1'),
    pytest.param(Key.L2, (Key.BACK, Key.L2), AudioPlayRecordingAction, id='back+l2'),
    pytest.param(
        Key.L3, (Key.BACK, Key.L3), ReplayRecordedSequenceAction, id='back+l3',
    ),
    pytest.param(Key.BACK, (Key.HOME, Key.BACK), FinishEvent, id='home+back'),
    pytest.param(Key.UP, (Key.HOME, Key.UP), NotificationsAddAction, id='home+up'),
    pytest.param(
        Key.DOWN, (Key.HOME, Key.DOWN), NotificationsAddAction, id='home+down',
    ),
]


@pytest.mark.parametrize(('key', 'pressed_keys', 'expected'), _COMBOS)
def test_key_combinations_emit_expected_output(
    key: Key,
    pressed_keys: tuple[Key, ...],
    expected: type,
) -> None:
    """Each two-key chord maps to its dedicated action/event."""
    result = reducer(
        KeypadState(depth=1),
        KeypadKeyPressAction(key=key, pressed_keys=pressed_keys),
    )
    assert any(isinstance(item, expected) for item in _emitted(result))


class TestPassthroughs:
    """State-preserving fallthrough branches."""

    def test_consumed_release_resets_the_flag(self) -> None:
        """A release while consumed clears the consumed flag and emits nothing."""
        result = reducer(
            KeypadState(is_consumed=True),
            KeypadKeyReleaseAction(key=Key.L1, pressed_keys=()),
        )
        assert isinstance(result, KeypadState)
        assert result.is_consumed is False

    def test_unhandled_press_combo_returns_state_unchanged(self) -> None:
        """A single BACK press (no dedicated case) leaves the state untouched."""
        state = KeypadState(depth=1)
        assert reducer(state, _press(Key.BACK)) is state

    def test_unknown_action_returns_state_unchanged(self) -> None:
        """An action matching no case leaves the state untouched."""
        state = KeypadState(depth=1)
        assert reducer(state, InitAction()) is state
