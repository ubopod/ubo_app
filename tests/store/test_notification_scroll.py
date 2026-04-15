"""Tests for notification scrolling behavior.

Covers single-page text scroll (ApplicationScrollEvent) and
multi-page item scroll (page_index changes with StackPageIndexChangedEvent).
"""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitAction

from ubo_app.store.core.types import (
    ApplicationScrollEvent,
    MainState,
    MenuScrollAction,
    MenuScrollDirection,
    NotificationStackItem,
    NotificationViewData,
    StackPageIndexChangedEvent,
    StackPushNotificationAction,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _import_reducer() -> Callable:
    """Import the reducer, working around the circular import."""
    menus_key = 'ubo_app.store.core.menus'
    already_loaded = menus_key in sys.modules
    modules_before = set(sys.modules)

    if not already_loaded:
        from types import ModuleType

        fake_menus = ModuleType(menus_key)
        sys.modules[menus_key] = fake_menus

    from ubo_app.store.core.reducer import reducer as _reducer

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


def _push_notification(state: MainState, notification_id: str) -> MainState:
    """Push a notification onto the stack."""
    return _get_state(
        reducer(state, StackPushNotificationAction(notification_id=notification_id)),
    )


class TestSinglePageNotificationScroll:
    """Tests for scrolling single-page notifications (text overflow)."""

    def test_scroll_down_emits_application_scroll_event(self) -> None:
        """Single-page notification scroll DOWN emits ApplicationScrollEvent."""
        state = _push_notification(_init_state(), 'n1')
        state = replace(
            state,
            current_view=NotificationViewData(
                notification_id='n1',
                total_pages=1,
            ),
        )

        result = reducer(
            state,
            MenuScrollAction(direction=MenuScrollDirection.DOWN),
        )

        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], ApplicationScrollEvent)
        assert events[0].direction == 'down'
        # State should be unchanged (no page_index change)
        assert _get_state(result) is state

    def test_scroll_up_emits_application_scroll_event(self) -> None:
        """Single-page notification scroll UP emits ApplicationScrollEvent."""
        state = _push_notification(_init_state(), 'n1')
        state = replace(
            state,
            current_view=NotificationViewData(
                notification_id='n1',
                total_pages=1,
            ),
        )

        result = reducer(
            state,
            MenuScrollAction(direction=MenuScrollDirection.UP),
        )

        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], ApplicationScrollEvent)
        assert events[0].direction == 'up'
        assert _get_state(result) is state


class TestMultiPageNotificationScroll:
    """Tests for scrolling multi-page notifications (>3 items)."""

    def test_scroll_down_advances_page(self) -> None:
        """Scroll DOWN on page 0 of 2-page notification advances to page 1."""
        state = _push_notification(_init_state(), 'n1')
        state = replace(
            state,
            current_view=NotificationViewData(
                notification_id='n1',
                page_index=0,
                total_pages=2,
            ),
        )

        result = reducer(
            state,
            MenuScrollAction(direction=MenuScrollDirection.DOWN),
        )
        new_state = _get_state(result)
        top = new_state.stack[-1]

        assert isinstance(top, NotificationStackItem)
        assert top.page_index == 1

        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], StackPageIndexChangedEvent)
        assert events[0].page_index == 1

    def test_scroll_up_goes_back(self) -> None:
        """Scroll UP on page 1 goes back to page 0."""
        state = _push_notification(_init_state(), 'n1')
        # Set page_index to 1
        top = state.stack[-1]
        assert isinstance(top, NotificationStackItem)
        state = replace(
            state,
            stack=(*state.stack[:-1], replace(top, page_index=1)),
            current_view=NotificationViewData(
                notification_id='n1',
                page_index=1,
                total_pages=2,
            ),
        )

        result = reducer(
            state,
            MenuScrollAction(direction=MenuScrollDirection.UP),
        )
        new_state = _get_state(result)
        new_top = new_state.stack[-1]

        assert isinstance(new_top, NotificationStackItem)
        assert new_top.page_index == 0

    def test_scroll_wraps_around_forward(self) -> None:
        """Scroll DOWN on last page wraps to page 0."""
        state = _push_notification(_init_state(), 'n1')
        top = state.stack[-1]
        assert isinstance(top, NotificationStackItem)
        state = replace(
            state,
            stack=(*state.stack[:-1], replace(top, page_index=1)),
            current_view=NotificationViewData(
                notification_id='n1',
                page_index=1,
                total_pages=2,
            ),
        )

        result = reducer(
            state,
            MenuScrollAction(direction=MenuScrollDirection.DOWN),
        )
        new_state = _get_state(result)
        new_top = new_state.stack[-1]

        assert isinstance(new_top, NotificationStackItem)
        assert new_top.page_index == 0

    def test_scroll_wraps_around_backward(self) -> None:
        """Scroll UP on page 0 wraps to last page."""
        state = _push_notification(_init_state(), 'n1')
        state = replace(
            state,
            current_view=NotificationViewData(
                notification_id='n1',
                page_index=0,
                total_pages=3,
            ),
        )

        result = reducer(
            state,
            MenuScrollAction(direction=MenuScrollDirection.UP),
        )
        new_state = _get_state(result)
        new_top = new_state.stack[-1]

        assert isinstance(new_top, NotificationStackItem)
        assert new_top.page_index == 2
