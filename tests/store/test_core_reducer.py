"""Tests for the main reducer in reducer.py.

These tests call the reducer function directly with various actions
and assert on the resulting state and events.

NOTE: reducer.py imports HOME_MENU from menus.py which triggers store
initialization. We use a lazy import inside _get_reducer() to break the
circular import, and replace HOME_MENU with a test menu after init.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from redux import CompleteReducerResult, InitAction, InitializationActionError
from ubo_gui.menu.types import HeadlessMenu, SubMenuItem

from ubo_app.store.core.types import (
    ApplicationViewData,
    CloseApplicationAction,
    CloseApplicationEvent,
    MainAction,
    MainState,
    MenuChooseByIconAction,
    MenuChooseByIconEvent,
    MenuChooseByLabelAction,
    MenuChooseByLabelEvent,
    MenuGoBackAction,
    MenuGoBackEvent,
    MenuGoHomeAction,
    MenuGoHomeEvent,
    MenuViewData,
    NotificationViewData,
    OpenApplicationAction,
    OpenApplicationEvent,
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
    ViewChangedEvent,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# Test menu tree
TEST_MENU = HeadlessMenu(
    title='Home',
    items=[
        SubMenuItem(key='main', label='Main', icon='M', sub_menu=HeadlessMenu(
            title='Main',
            items=[
                SubMenuItem(key='apps', label='Apps', icon='A',
                            sub_menu=HeadlessMenu(title='Apps', items=[])),
                SubMenuItem(key='settings', label='Settings', icon='S',
                            sub_menu=HeadlessMenu(title='Settings', items=[])),
            ],
        )),
        SubMenuItem(key='notifications', label='Notifications', icon='N',
                    sub_menu=HeadlessMenu(title='Notifications', items=[])),
    ],
)


def _import_reducer() -> Callable:
    """Import the reducer, working around the circular import.

    reducer.py -> menus.py -> store.main -> reducer.py is circular.
    We pre-populate sys.modules with a fake menus module that has HOME_MENU,
    import the reducer, then clean up ALL newly loaded modules so they don't
    interfere with integration tests.
    """
    menus_key = 'ubo_app.store.core.menus'
    already_loaded = menus_key in sys.modules
    modules_before = set(sys.modules)

    if not already_loaded:
        from types import ModuleType

        fake_menus = ModuleType(menus_key)
        fake_menus.HOME_MENU = TEST_MENU  # type: ignore[attr-defined]
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
    """Create an initialized state with TEST_MENU."""
    result = reducer(None, InitAction())
    assert isinstance(result, MainState)
    return replace(result, menu=TEST_MENU)


def _get_state(result: object) -> MainState:
    """Extract state from reducer result."""
    if isinstance(result, CompleteReducerResult):
        return result.state
    assert isinstance(result, MainState)
    return result


def _get_events(result: object) -> list:
    """Extract events from reducer result."""
    if isinstance(result, CompleteReducerResult):
        return list(result.events)
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

    def test_init_sets_menu(self) -> None:
        """Verify InitAction sets the menu on the state."""
        state = _get_state(reducer(None, InitAction()))
        assert state.menu is not None

    def test_non_init_on_none_state_raises(self) -> None:
        """Verify non-init action on None state raises error."""
        with pytest.raises(InitializationActionError):
            reducer(None, StackPopAction())


class TestMenuActions:
    """Tests for menu navigation actions that emit events without state change."""

    def test_go_back_emits_event(self) -> None:
        """Verify MenuGoBackAction emits a MenuGoBackEvent."""
        state = _init_state()
        result = reducer(state, MenuGoBackAction())
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], MenuGoBackEvent)

    def test_go_back_does_not_change_state(self) -> None:
        """Verify MenuGoBackAction does not modify the stack."""
        state = _init_state()
        new_state = _get_state(reducer(state, MenuGoBackAction()))
        assert new_state.stack == state.stack

    def test_go_home_emits_event(self) -> None:
        """Verify MenuGoHomeAction emits a MenuGoHomeEvent."""
        state = _init_state()
        result = reducer(state, MenuGoHomeAction())
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], MenuGoHomeEvent)

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

    def test_push_menu_updates_view(self) -> None:
        """Verify pushing a menu updates current_view to MenuViewData."""
        state = _init_state()
        new_state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        assert isinstance(new_state.current_view, MenuViewData)

    def test_push_menu_emits_stack_and_view_events(self) -> None:
        """Verify pushing a menu emits stack and view changed events."""
        state = _init_state()
        result = reducer(state, StackPushMenuAction(menu_key='main'))
        events = _get_events(result)
        event_types = [type(e) for e in events]
        assert StackChangedEvent in event_types
        assert ViewChangedEvent in event_types

    def test_push_application_emits_events(self) -> None:
        """Verify pushing an application emits the expected events."""
        state = _init_state()
        result = reducer(state, StackPushApplicationAction(
            application_id='camera:viewfinder',
        ))
        events = _get_events(result)
        event_types = [type(e) for e in events]
        assert StackChangedEvent in event_types
        assert ViewChangedEvent in event_types

    def test_push_application_view_is_application(self) -> None:
        """Verify pushing an application sets ApplicationViewData."""
        state = _init_state()
        new_state = _get_state(reducer(state, StackPushApplicationAction(
            application_id='test:app',
        )))
        assert isinstance(new_state.current_view, ApplicationViewData)
        assert new_state.current_view.application_id == 'test:app'

    def test_push_notification_view_is_notification(self) -> None:
        """Verify pushing a notification sets NotificationViewData."""
        state = _init_state()
        new_state = _get_state(reducer(state, StackPushNotificationAction(
            notification_id='notif-1',
        )))
        assert isinstance(new_state.current_view, NotificationViewData)
        assert new_state.current_view.notification_id == 'notif-1'


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
        """Verify pop emits stack and view changed events."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        result = reducer(state, StackPopAction())
        events = _get_events(result)
        event_types = [type(e) for e in events]
        assert StackChangedEvent in event_types
        assert ViewChangedEvent in event_types

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
        """Verify setting page index updates the current view."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        result = reducer(state, StackSetPageIndexAction(page_index=1))
        new_state = _get_state(result)
        assert isinstance(new_state.current_view, MenuViewData)

    def test_set_page_index_emits_events(self) -> None:
        """Verify setting page index emits page and view events."""
        state = _init_state()
        state = _get_state(reducer(state, StackPushMenuAction(menu_key='main')))
        result = reducer(state, StackSetPageIndexAction(page_index=1))
        events = _get_events(result)
        event_types = [type(e) for e in events]
        assert StackPageIndexChangedEvent in event_types
        assert ViewChangedEvent in event_types

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

    def test_open_application_emits_event(self) -> None:
        """Verify OpenApplicationAction emits an OpenApplicationEvent."""
        state = _init_state()
        result = reducer(state, OpenApplicationAction(
            application_id='test:app',
            initialization_args=('a',),
        ))
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], OpenApplicationEvent)
        assert events[0].application_id == 'test:app'
        assert events[0].initialization_args == ('a',)

    def test_close_application_emits_event(self) -> None:
        """Verify CloseApplicationAction emits a CloseApplicationEvent."""
        state = _init_state()
        result = reducer(state, CloseApplicationAction(
            application_instance_id='inst-1',
        ))
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], CloseApplicationEvent)
        assert events[0].application_instance_id == 'inst-1'


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
        """Verify actions dispatched during recording are captured."""
        state = _init_state()
        state = _get_state(reducer(state, ToggleRecordingAction()))
        # Dispatch some actions while recording
        state = _get_state(reducer(state, MenuGoBackAction()))
        state = _get_state(reducer(state, MenuGoHomeAction()))
        # The recorded_sequence should have the actions
        # (including ToggleRecording toggle)
        assert len(state.recorded_sequence) > 0

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
