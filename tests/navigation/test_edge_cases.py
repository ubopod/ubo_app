"""Tests for navigation edge cases.

Boundaries, deep nesting, rapid operations, and error handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    HomeViewData,
    MenuStackItem,
    MenuViewData,
    StackPopAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner


class TestPopAtRoot:
    """Tests for pop operations when already at root."""

    def test_pop_at_root_is_noop(self, nav: ReducerRunner) -> None:
        """Verify popping at root does not change stack or path."""
        original = nav.state
        nav.dispatch(StackPopAction())
        assert nav.state.stack == original.stack
        assert nav.state.path == original.path
        assert nav.last_events == []

    def test_pop_to_root_at_root_is_noop(self, nav: ReducerRunner) -> None:
        """Verify pop-to-root at root does not change stack."""
        original = nav.state
        nav.dispatch(StackPopToRootAction())
        assert nav.state.stack == original.stack
        assert nav.last_events == []


class TestPushPopRoundTrip:
    """Tests for push + immediate pop returning to original state."""

    def test_push_pop_returns_to_original_path(self, nav: ReducerRunner) -> None:
        """Verify push followed by pop restores the original path."""
        original_path = nav.state.path
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPopAction())
        assert nav.state.path == original_path

    def test_push_pop_returns_to_original_stack_length(
        self, nav: ReducerRunner,
    ) -> None:
        """Verify push followed by pop restores the original stack length."""
        original_len = len(nav.state.stack)
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPopAction())
        assert len(nav.state.stack) == original_len

    def test_push_pop_preserves_root(self, nav: ReducerRunner) -> None:
        """Verify push followed by pop preserves the root stack item."""
        original_root = nav.state.stack[0]
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPopAction())
        assert nav.state.stack[0] is original_root


class TestDeepNesting:
    """Tests for deeply nested navigation."""

    def test_ten_levels_deep(self, nav: ReducerRunner) -> None:
        """Push 10 menu items and verify stack length."""
        for i in range(10):
            nav.dispatch(StackPushMenuAction(menu_key=f'level_{i}'))
        assert len(nav.state.stack) == 11  # root + 10

    def test_pop_all_ten_levels(self, nav: ReducerRunner) -> None:
        """Verify pop-to-root from 10 levels deep returns to root."""
        for i in range(10):
            nav.dispatch(StackPushMenuAction(menu_key=f'level_{i}'))
        nav.dispatch(StackPopToRootAction())
        assert len(nav.state.stack) == 1
        assert isinstance(nav.view, HomeViewData)

    def test_pop_count_exceeding_stack(self, nav: ReducerRunner) -> None:
        """StackPopAction(count=100) with only 3 items keeps root."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPopAction(count=100))
        assert len(nav.state.stack) == 1
        assert nav.state.path == ()


class TestRapidOperations:
    """Tests for rapid sequential push/pop operations."""

    def test_rapid_push_pop_sequence(self, nav: ReducerRunner) -> None:
        """Rapid push/pop should leave state consistent."""
        for _ in range(20):
            nav.dispatch(StackPushMenuAction(menu_key='main'))
            nav.dispatch(StackPopAction())
        assert len(nav.state.stack) == 1
        assert nav.state.path == ()
        assert isinstance(nav.view, HomeViewData)

    def test_rapid_push_then_pop_to_root(self, nav: ReducerRunner) -> None:
        """Verify pop-to-root after 15 rapid pushes returns to root."""
        for i in range(15):
            nav.dispatch(StackPushMenuAction(menu_key=f'level_{i}'))
        nav.dispatch(StackPopToRootAction())
        assert len(nav.state.stack) == 1
        assert nav.state.path == ()

    def test_alternating_menu_and_app(self, nav: ReducerRunner) -> None:
        """Verify alternating menu and app pushes produce correct stack and path."""
        for i in range(10):
            nav.dispatch(StackPushMenuAction(menu_key=f'menu_{i}'))
            nav.dispatch(StackPushApplicationAction(
                application_id=f'app_{i}',
            ))
        # 1 root + 10 menus + 10 apps = 21
        assert len(nav.state.stack) == 21
        # Path only has menu keys
        assert len(nav.state.path) == 10


class TestInvalidMenuKey:
    """Tests for pushing invalid menu keys."""

    def test_invalid_key_still_pushes(self, nav: ReducerRunner) -> None:
        """Push with invalid key still adds to stack."""
        nav.dispatch(StackPushMenuAction(menu_key='nonexistent'))
        assert len(nav.state.stack) == 2
        # View computation can't find the menu, returns empty MenuViewData
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.items == ()

    def test_path_includes_invalid_key(self, nav: ReducerRunner) -> None:
        """Path reflects the key even if the menu doesn't exist."""
        nav.dispatch(StackPushMenuAction(menu_key='nonexistent'))
        assert nav.state.path == ('nonexistent',)


class TestMixedEdgeCases:
    """Additional edge cases for mixed operations."""

    def test_notification_over_deep_menu_then_pop_all(
        self, nav: ReducerRunner,
    ) -> None:
        """Verify pop-to-root clears notification and menu items from stack."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPushNotificationAction(notification_id='n1'))
        nav.dispatch(StackPopToRootAction())
        assert len(nav.state.stack) == 1
        assert isinstance(nav.view, HomeViewData)

    def test_stack_item_ids_are_unique(self, nav: ReducerRunner) -> None:
        """Verify all stack items have unique IDs after mixed pushes."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPushApplicationAction(application_id='app'))
        ids = [item.id for item in nav.state.stack]
        assert len(ids) == len(set(ids))  # All unique

    def test_root_menu_key_is_empty(self, nav: ReducerRunner) -> None:
        """Verify the root stack item has an empty menu key."""
        root = nav.state.stack[0]
        assert isinstance(root, MenuStackItem)
        assert root.menu_key == ''
