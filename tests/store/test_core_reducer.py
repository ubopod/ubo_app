"""Tests for the main reducer in reducer.py.

These tests call the reducer function directly with various actions
and assert on the resulting state and events.

NOTE: reducer.py imports from menus.py which triggers store
initialization. We use a lazy import inside _get_reducer() to break the
circular import.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.core.types import (
    ApplicationStackItem,
    CloseApplicationAction,
    MainAction,
    MainState,
    MenuChooseByIconAction,
    MenuChooseByIconEvent,
    MenuChooseByLabelAction,
    MenuChooseByLabelEvent,
    MenuGoBackAction,
    MenuGoHomeAction,
    OpenApplicationAction,
    PowerOffAction,
    PowerOffEvent,
    RebootAction,
    RebootEvent,
    ReplayRecordedSequenceAction,
    ReplayRecordedSequenceEvent,
    ReportReplayingDoneAction,
    SetAreEnclosuresVisibleAction,
    StackChangedEvent,
    StackPageIndexChangedEvent,
    StackPopAction,
    StackPopItemAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackSetPageIndexAction,
    StoreRecordedSequenceEvent,
    ToggleRecordingAction,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _import_reducer() -> Callable:
    """Import the reducer, working around the circular import.

    reducer.py -> menus.py -> store.main -> reducer.py is circular.
    We pre-populate sys.modules with a fake menus module,
    import the reducer, then clean up ALL newly loaded modules so they don't
    interfere with integration tests.
    """
    menus_key = 'ubo_app.store.core.menus'
    already_loaded = menus_key in sys.modules
    modules_before = set(sys.modules)

    if not already_loaded:
        from types import ModuleType

        fake_menus = ModuleType(menus_key)
        sys.modules[menus_key] = fake_menus

    from ubo_app.store.core.reducer import reducer as _reducer

    # Clean up: remove ALL modules loaded during this import so they
    # don't interfere with integration tests that need real modules
    if not already_loaded:
        for mod in set(sys.modules) - modules_before:
            del sys.modules[mod]

    return _reducer


reducer = _import_reducer()


def _init_state() -> MainState:
    """Create an initialized state."""
    result = reducer(None, InitAction())
    assert isinstance(result, MainState)
    return result


def _get_state(result: object) -> MainState:
    """Extract state from reducer result."""
    if isinstance(result, MainState):
        return result
    assert isinstance(result, CompleteReducerResult)
    state = result.state  # pyright: ignore[reportAttributeAccessIssue]
    assert isinstance(state, MainState)
    return state


def _get_events(result: object) -> list:
    """Extract events from reducer result."""
    if isinstance(result, CompleteReducerResult):
        return list(result.events or ())  # pyright: ignore[reportAttributeAccessIssue]
    return []


class TestInitAction:
    """Tests for InitAction handling."""

    def test_init_creates_state(self) -> None:
        """Verify InitAction creates a MainState."""
        result = reducer(None, InitAction())
        assert isinstance(result, MainState)

    def test_init_creates_stack_with_root(self) -> None:
        """Verify InitAction creates a stack with one root item."""
        state = _get_state(reducer(None, InitAction()))
        assert len(state.stack) == 1

    def test_non_init_on_none_state_raises(self) -> None:
        """Verify non-init action on None state raises error."""
        with pytest.raises(InitializationActionError):
            reducer(None, StackPopAction())


class TestMenuActions:
    """Tests for menu navigation actions handled directly by the reducer."""

    def test_go_back_pops_stack(self) -> None:
        """Verify MenuGoBackAction pops the stack when not at root."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        assert len(state.stack) == 2
        result = reducer(state, MenuGoBackAction())
        new_state = _get_state(result)
        assert len(new_state.stack) == 1
        events = _get_events(result)
        assert any(isinstance(e, StackChangedEvent) for e in events)

    def test_go_back_at_root_is_noop(self) -> None:
        """Verify MenuGoBackAction at root returns unchanged state."""
        state = _init_state()
        result = reducer(state, MenuGoBackAction())
        new_state = _get_state(result)
        assert new_state.stack == state.stack
        assert _get_events(result) == []

    def test_go_home_pops_to_root(self) -> None:
        """Verify MenuGoHomeAction pops to root."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='apps')))
        assert len(state.stack) == 3
        result = reducer(state, MenuGoHomeAction())
        new_state = _get_state(result)
        assert len(new_state.stack) == 1
        events = _get_events(result)
        assert any(isinstance(e, StackChangedEvent) for e in events)

    def test_go_home_at_root_is_noop(self) -> None:
        """Verify MenuGoHomeAction at root returns unchanged state."""
        state = _init_state()
        result = reducer(state, MenuGoHomeAction())
        new_state = _get_state(result)
        assert new_state.stack == state.stack
        assert _get_events(result) == []

    def test_choose_by_icon_emits_event(self) -> None:
        """Verify MenuChooseByIconAction emits the correct event."""
        state = _init_state()
        result = reducer(state, MenuChooseByIconAction(icon='M'))
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], MenuChooseByIconEvent)
        assert events[0].icon == 'M'

    def test_choose_by_label_emits_event(self) -> None:
        """Verify MenuChooseByLabelAction emits the correct event."""
        state = _init_state()
        result = reducer(state, MenuChooseByLabelAction(label='Settings'))
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], MenuChooseByLabelEvent)
        assert events[0].label == 'Settings'


class TestStackPushActions:
    """Tests for stack push actions."""

    def test_push_menu_grows_stack(self) -> None:
        """Verify StackPushMenuAction increases the stack size."""
        state = _init_state()
        new_state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        assert len(new_state.stack) == 2

    def test_push_menu_emits_stack_event(self) -> None:
        """Verify pushing a menu emits a stack changed event."""
        state = _init_state()
        result = reducer(state, StackPushMenuAction(menu_key='main'))
        events = _get_events(result)
        event_types = [type(e) for e in events]
        assert StackChangedEvent in event_types

    def test_push_application_emits_events(self) -> None:
        """Verify pushing an application emits the expected events."""
        state = _init_state()
        result = reducer(state, StackPushApplicationAction(
            application_id='camera:viewfinder',
        ))
        events = _get_events(result)
        event_types = [type(e) for e in events]
        assert StackChangedEvent in event_types

    def test_push_application_grows_stack(self) -> None:
        """Verify pushing an application grows the stack."""
        state = _init_state()
        new_state = _get_state(reducer(state, StackPushApplicationAction(
            application_id='test:app',
        )))
        assert len(new_state.stack) == 2

    def test_push_notification_grows_stack(self) -> None:
        """Verify pushing a notification grows the stack."""
        state = _init_state()
        new_state = _get_state(reducer(state, StackPushNotificationAction(
            notification_id='notif-1',
        )))
        assert len(new_state.stack) == 2


class TestStackPopActions:
    """Tests for stack pop actions."""

    def test_pop_at_root_returns_unchanged(self) -> None:
        """Verify pop at root returns unchanged state with no events."""
        state = _init_state()
        result = reducer(state, StackPopAction())
        new_state = _get_state(result)
        assert new_state.stack == state.stack
        assert _get_events(result) == []

    def test_pop_from_submenu(self) -> None:
        """Verify pop from a submenu reduces the stack by one."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        result = reducer(state, StackPopAction())
        new_state = _get_state(result)
        assert len(new_state.stack) == 1

    def test_pop_emits_events(self) -> None:
        """Verify pop emits stack changed event."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        result = reducer(state, StackPopAction())
        events = _get_events(result)
        event_types = [type(e) for e in events]
        assert StackChangedEvent in event_types

    def test_pop_to_root_from_deep(self) -> None:
        """Verify pop to root clears all items above root."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='apps')))
        result = reducer(state, StackPopToRootAction())
        new_state = _get_state(result)
        assert len(new_state.stack) == 1
        assert new_state.path == ()

    def test_pop_to_root_at_root_unchanged(self) -> None:
        """Verify pop to root at root returns unchanged state."""
        state = _init_state()
        result = reducer(state, StackPopToRootAction())
        new_state = _get_state(result)
        assert new_state.stack == state.stack
        assert _get_events(result) == []

    def test_pop_item_removes_specific(self) -> None:
        """Verify pop item removes the item with the given id."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        item_id = state.stack[-1].id
        result = reducer(state, StackPopItemAction(item_id=item_id))
        new_state = _get_state(result)
        assert len(new_state.stack) == 1
        assert all(i.id != item_id for i in new_state.stack)

    def test_pop_item_not_found_unchanged(self) -> None:
        """Verify pop item with unknown id returns unchanged state."""
        state = _init_state()
        result = reducer(state, StackPopItemAction(item_id='nonexistent'))
        new_state = _get_state(result)
        assert new_state.stack == state.stack
        assert _get_events(result) == []


class TestSetPageIndex:
    """Tests for StackSetPageIndexAction."""

    def test_set_page_index(self) -> None:
        """Verify setting page index works."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        result = reducer(state, StackSetPageIndexAction(page_index=1))
        events = _get_events(result)
        event_types = [type(e) for e in events]
        assert StackPageIndexChangedEvent in event_types

    def test_set_page_index_on_non_menu_unchanged(self) -> None:
        """Verify setting page index on non-menu top is a no-op."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushApplicationAction(
            application_id='test:app',
        )))
        result = reducer(state, StackSetPageIndexAction(page_index=1))
        new_state = _get_state(result)
        assert new_state.stack == state.stack
        assert _get_events(result) == []


class TestOpenCloseApplication:
    """Tests for OpenApplicationAction and CloseApplicationAction."""

    def test_open_application_pushes_stack(self) -> None:
        """Verify OpenApplicationAction pushes an ApplicationStackItem."""
        state = _init_state()
        result = reducer(state, OpenApplicationAction(
            application_id='test:app',
            initialization_args=('a',),
        ))
        new_state = _get_state(result)
        assert len(new_state.stack) == 2
        top = new_state.stack[-1]
        assert isinstance(top, ApplicationStackItem)
        assert top.application_id == 'test:app'
        assert top.initialization_args == ('a',)
        events = _get_events(result)
        assert any(isinstance(e, StackChangedEvent) for e in events)

    def test_close_application_pops_matching_item(self) -> None:
        """Verify CloseApplicationAction removes the matching stack item."""
        state = _init_state()
        state = _get_state(reducer(state, OpenApplicationAction(
            application_id='test:app',
        )))
        assert len(state.stack) == 2
        app_item_id = state.stack[-1].id
        result = reducer(state, CloseApplicationAction(
            application_instance_id=app_item_id,
        ))
        new_state = _get_state(result)
        assert len(new_state.stack) == 1
        events = _get_events(result)
        assert any(isinstance(e, StackChangedEvent) for e in events)

    def test_close_application_not_found_is_noop(self) -> None:
        """Verify CloseApplicationAction with unknown id is a no-op."""
        state = _init_state()
        result = reducer(state, CloseApplicationAction(
            application_instance_id='nonexistent',
        ))
        new_state = _get_state(result)
        assert new_state.stack == state.stack
        assert _get_events(result) == []


class TestToggleRecording:
    """Tests for recording toggle."""

    def test_toggle_starts_recording(self) -> None:
        """Verify first toggle starts recording."""
        state = _init_state()
        new_state = _get_state(reducer(state, ToggleRecordingAction()))
        assert new_state.is_recording is True

    def test_toggle_stops_recording_and_emits(self) -> None:
        """Verify second toggle stops recording and emits event."""
        state = _init_state()
        state = _get_state(reducer(state, ToggleRecordingAction()))
        assert state.is_recording is True
        result = reducer(state, ToggleRecordingAction())
        new_state = _get_state(result)
        assert new_state.is_recording is False
        events = _get_events(result)
        assert any(isinstance(e, StoreRecordedSequenceEvent) for e in events)

    def test_recording_captures_actions(self) -> None:
        """Verify KeypadAction dispatched during recording are captured."""
        from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

        state = _init_state()
        state = _get_state(reducer(state, ToggleRecordingAction()))
        # Dispatch keypad actions while recording (only KeypadAction captured)
        state = _get_state(
            reducer(
                state,
                KeypadKeyPressAction(key=Key.L1, pressed_keys=(Key.L1,)),
            ),
        )
        # The recorded_sequence should have the keypad action
        assert len(state.recorded_sequence) == 1

    def test_toggle_during_replaying_noop(self) -> None:
        """Verify toggle recording is a no-op while replaying."""
        state = _init_state()
        state = replace(state, is_replaying=True)
        new_state = _get_state(reducer(state, ToggleRecordingAction()))
        assert new_state.is_recording is False


class TestReplayRecording:
    """Tests for replay actions."""

    def test_replay_sets_replaying(self) -> None:
        """Verify replay action sets is_replaying to True."""
        state = _init_state()
        result = reducer(state, ReplayRecordedSequenceAction())
        new_state = _get_state(result)
        assert new_state.is_replaying is True

    def test_replay_emits_event(self) -> None:
        """Verify replay action emits ReplayRecordedSequenceEvent."""
        state = _init_state()
        result = reducer(state, ReplayRecordedSequenceAction())
        events = _get_events(result)
        assert any(isinstance(e, ReplayRecordedSequenceEvent) for e in events)

    def test_replay_during_recording_noop(self) -> None:
        """Verify replay is a no-op while recording."""
        state = _init_state()
        state = replace(state, is_recording=True)
        new_state = _get_state(reducer(state, ReplayRecordedSequenceAction()))
        assert new_state.is_replaying is False

    def test_replay_during_replaying_noop(self) -> None:
        """Verify replay is a no-op when already replaying."""
        state = _init_state()
        state = replace(state, is_replaying=True)
        new_state = _get_state(reducer(state, ReplayRecordedSequenceAction()))
        # Still replaying, no change
        assert new_state.is_replaying is True

    def test_report_replaying_done(self) -> None:
        """Verify ReportReplayingDoneAction clears is_replaying."""
        state = _init_state()
        state = _get_state(reducer(state, ReplayRecordedSequenceAction()))
        assert state.is_replaying is True
        new_state = _get_state(reducer(state, ReportReplayingDoneAction()))
        assert new_state.is_replaying is False


class TestPowerActions:
    """Tests for power actions."""

    def test_power_off_emits_event(self) -> None:
        """Verify PowerOffAction emits a PowerOffEvent."""
        state = _init_state()
        result = reducer(state, PowerOffAction())
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], PowerOffEvent)

    def test_reboot_emits_event(self) -> None:
        """Verify RebootAction emits a RebootEvent."""
        state = _init_state()
        result = reducer(state, RebootAction())
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], RebootEvent)


class TestEnclosureVisibility:
    """Tests for SetAreEnclosuresVisibleAction."""

    def test_set_visibility(self) -> None:
        """Verify setting enclosure visibility to False works."""
        state = _init_state()
        new_state = _get_state(
            reducer(state, SetAreEnclosuresVisibleAction(
                is_header_visible=False,
                is_footer_visible=False,
            )),
        )
        assert new_state.is_header_visible is False
        assert new_state.is_footer_visible is False

    def test_restore_visibility(self) -> None:
        """Verify restoring enclosure visibility to True works."""
        state = _init_state()
        state = replace(state, is_header_visible=False, is_footer_visible=False)
        new_state = _get_state(
            reducer(state, SetAreEnclosuresVisibleAction(
                is_header_visible=True,
                is_footer_visible=True,
            )),
        )
        assert new_state.is_header_visible is True
        assert new_state.is_footer_visible is True


class TestUnknownAction:
    """Tests for unhandled actions."""

    def test_unknown_action_returns_state(self) -> None:
        """Verify unknown action returns the state unchanged."""
        state = _init_state()

        class UnknownAction(MainAction):
            pass

        result = reducer(state, UnknownAction())
        new_state = _get_state(result)
        assert new_state.stack == state.stack
