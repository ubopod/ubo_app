"""Tests for event emission during navigation.

Verifies that correct events are emitted for stack operations.

NOTE: ViewChangedEvent is no longer emitted inline by the reducer.
It is now emitted by the view autorun in view_computation.py when
it dispatches UpdateCurrentViewAction. Stack operations only emit
StackChangedEvent (and StackPageIndexChangedEvent for page changes).

MenuGoBackAction, MenuGoHomeAction, MenuScrollAction, OpenApplicationAction,
and CloseApplicationAction now perform state changes directly in the reducer
instead of emitting intermediate events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    MenuChooseByIconAction,
    MenuChooseByIconEvent,
    MenuGoBackAction,
    MenuGoHomeAction,
    StackChangedEvent,
    StackPageIndexChangedEvent,
    StackPopAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackSetPageIndexAction,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import EventCapture, ReducerRunner


class TestPushEvents:
    """Tests for events emitted on push operations."""

    def test_push_menu_emits_stack_changed(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify pushing a menu emits a StackChangedEvent."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        stack_events = events.capture_from(nav, StackChangedEvent)
        assert len(stack_events) == 1
        assert stack_events[0].stack == nav.state.stack

    def test_push_app_emits_stack_changed(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify pushing an app emits StackChangedEvent."""
        nav.dispatch(StackPushApplicationAction(application_id='test:app'))
        stack_events = events.capture_from(nav, StackChangedEvent)
        assert len(stack_events) == 1

    def test_push_notification_emits_stack_changed(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify pushing a notification emits StackChangedEvent."""
        nav.dispatch(StackPushNotificationAction(notification_id='n1'))
        stack_events = events.capture_from(nav, StackChangedEvent)
        assert len(stack_events) == 1


class TestPopEvents:
    """Tests for events emitted on pop operations."""

    def test_pop_emits_stack_changed(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify popping emits a StackChangedEvent."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.clear_events()
        nav.dispatch(StackPopAction())
        stack_events = events.capture_from(nav, StackChangedEvent)
        assert len(stack_events) == 1

    def test_pop_at_root_no_events(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify popping at root emits no events."""
        nav.dispatch(StackPopAction())
        stack_events = events.capture_from(nav, StackChangedEvent)
        assert len(stack_events) == 0

    def test_pop_to_root_emits_stack_changed(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify pop-to-root emits a StackChangedEvent."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.clear_events()
        nav.dispatch(StackPopToRootAction())
        stack_events = events.capture_from(nav, StackChangedEvent)
        assert len(stack_events) == 1

    def test_pop_to_root_at_root_no_events(
        self, nav: ReducerRunner, events: EventCapture,  # noqa: ARG002
    ) -> None:
        """Verify pop-to-root at root emits no events."""
        nav.dispatch(StackPopToRootAction())
        assert nav.last_events == []


class TestPageIndexEvents:
    """Tests for page index change events."""

    def test_set_page_index_emits_page_changed(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify setting page index emits a StackPageIndexChangedEvent."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.clear_events()
        nav.dispatch(StackSetPageIndexAction(page_index=1))
        page_events = events.capture_from(nav, StackPageIndexChangedEvent)
        assert len(page_events) == 1
        assert page_events[0].page_index == 1


class TestMenuActionEvents:
    """Tests for menu actions that now change state directly."""

    def test_go_back_emits_stack_changed(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify MenuGoBackAction emits StackChangedEvent when not at root."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.clear_events()
        nav.dispatch(MenuGoBackAction())
        stack_events = events.capture_from(nav, StackChangedEvent)
        assert len(stack_events) == 1

    def test_go_back_at_root_no_events(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify MenuGoBackAction at root emits no events."""
        nav.dispatch(MenuGoBackAction())
        stack_events = events.capture_from(nav, StackChangedEvent)
        assert len(stack_events) == 0

    def test_go_home_emits_stack_changed(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify MenuGoHomeAction emits StackChangedEvent."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.clear_events()
        nav.dispatch(MenuGoHomeAction())
        stack_events = events.capture_from(nav, StackChangedEvent)
        assert len(stack_events) == 1

    def test_choose_by_icon_emits_event(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify MenuChooseByIconAction emits event with correct icon."""
        nav.dispatch(MenuChooseByIconAction(icon='M'))
        icon_events = events.capture_from(nav, MenuChooseByIconEvent)
        assert len(icon_events) == 1
        assert icon_events[0].icon == 'M'


class TestEventAccumulation:
    """Tests for event accumulation across multiple dispatches."""

    def test_all_events_accumulate(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify events accumulate across multiple dispatch calls."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPopAction())
        all_stack = events.all_of_type(nav, StackChangedEvent)
        # 2 pushes + 1 pop = 3 StackChangedEvents
        assert len(all_stack) == 3

    def test_clear_events_resets(
        self, nav: ReducerRunner, events: EventCapture,
    ) -> None:
        """Verify clearing events resets the accumulated event list."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.clear_events()
        all_events = events.all_of_type(nav, StackChangedEvent)
        assert len(all_events) == 0
