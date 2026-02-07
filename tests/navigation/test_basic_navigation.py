"""Tests for basic navigation flows.

Core push/pop/home flows using the ReducerRunner fixture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    HomeViewData,
    MenuViewData,
    StackPopAction,
    StackPopToRootAction,
    StackPushMenuAction,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner


class TestInitialState:
    """Tests for the initial navigation state."""

    def test_starts_at_home(self, nav: ReducerRunner) -> None:
        """Verify initial view is HomeViewData."""
        assert isinstance(nav.view, HomeViewData)

    def test_root_stack_has_one_item(self, nav: ReducerRunner) -> None:
        """Verify the root stack contains exactly one item."""
        assert len(nav.state.stack) == 1

    def test_path_is_empty(self, nav: ReducerRunner) -> None:
        """Verify the initial path is an empty tuple."""
        assert nav.state.path == ()

    def test_home_view_has_menu_items(self, nav: ReducerRunner) -> None:
        """Verify home view contains Main, Notifications, and Power items."""
        view = nav.view
        assert isinstance(view, HomeViewData)
        assert len(view.menu_items) == 3
        labels = [item.label for item in view.menu_items]
        assert 'Main' in labels
        assert 'Notifications' in labels
        assert 'Power' in labels


class TestPushNavigation:
    """Tests for navigating into submenus."""

    def test_push_to_main(self, nav: ReducerRunner) -> None:
        """Verify pushing to main menu produces a MenuViewData with correct path."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        assert isinstance(nav.view, MenuViewData)
        assert nav.state.path == ('main',)

    def test_push_to_main_settings(self, nav: ReducerRunner) -> None:
        """Verify navigating to main then settings produces the correct path."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        assert nav.state.path == ('main', 'settings')
        assert isinstance(nav.view, MenuViewData)

    def test_deep_navigation(self, nav: ReducerRunner) -> None:
        """Verify three-level deep navigation builds the correct path and title."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPushMenuAction(menu_key='network'))
        assert nav.state.path == ('main', 'settings', 'network')
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.title == 'Network'

    def test_push_grows_stack(self, nav: ReducerRunner) -> None:
        """Verify each push increases the stack length by one."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        assert len(nav.state.stack) == 2
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        assert len(nav.state.stack) == 3

    def test_menu_view_title(self, nav: ReducerRunner) -> None:
        """Verify the menu view title matches the pushed menu."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.title == 'Main'


class TestPopNavigation:
    """Tests for navigating back."""

    def test_pop_returns_to_previous(self, nav: ReducerRunner) -> None:
        """Verify popping returns to the previous menu path."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPopAction())
        assert nav.state.path == ('main',)

    def test_pop_to_home(self, nav: ReducerRunner) -> None:
        """Verify popping the only pushed menu returns to home view."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, HomeViewData)
        assert nav.state.path == ()

    def test_pop_multiple(self, nav: ReducerRunner) -> None:
        """Verify popping multiple items at once removes the correct count."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPushMenuAction(menu_key='network'))
        nav.dispatch(StackPopAction(count=2))
        assert nav.state.path == ('main',)

    def test_pop_at_root_is_noop(self, nav: ReducerRunner) -> None:
        """Verify popping at root does not change the stack."""
        original_stack = nav.state.stack
        nav.dispatch(StackPopAction())
        assert nav.state.stack == original_stack


class TestPopToRoot:
    """Tests for navigating directly to home."""

    def test_pop_to_root_from_deep(self, nav: ReducerRunner) -> None:
        """Verify pop-to-root from a deep stack returns to home with empty path."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPushMenuAction(menu_key='network'))
        nav.dispatch(StackPopToRootAction())
        assert len(nav.state.stack) == 1
        assert nav.state.path == ()
        assert isinstance(nav.view, HomeViewData)

    def test_pop_to_root_at_root_is_noop(self, nav: ReducerRunner) -> None:
        """Verify pop-to-root at root does not change the stack."""
        original_state = nav.state
        nav.dispatch(StackPopToRootAction())
        assert nav.state.stack == original_state.stack

    def test_pop_to_root_clears_path(self, nav: ReducerRunner) -> None:
        """Verify pop-to-root resets the path to an empty tuple."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPopToRootAction())
        assert nav.state.path == ()


class TestNavigationRoundTrips:
    """Tests for push-then-pop round trips."""

    def test_push_pop_returns_to_original(self, nav: ReducerRunner) -> None:
        """Verify a push followed by pop restores the original view and path."""
        original_view_type = type(nav.view)
        original_path = nav.state.path
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPopAction())
        assert type(nav.view) is original_view_type
        assert nav.state.path == original_path

    def test_multiple_round_trips(self, nav: ReducerRunner) -> None:
        """Verify repeated push-pop cycles always return to home."""
        for _ in range(5):
            nav.dispatch(StackPushMenuAction(menu_key='main'))
            nav.dispatch(StackPopAction())
        assert isinstance(nav.view, HomeViewData)
        assert nav.state.path == ()

    def test_path_tracks_navigation(self, nav: ReducerRunner) -> None:
        """Verify the path correctly tracks each push and pop operation."""
        paths = [nav.state.path]
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        paths.append(nav.state.path)
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        paths.append(nav.state.path)
        nav.dispatch(StackPopAction())
        paths.append(nav.state.path)
        nav.dispatch(StackPopAction())
        paths.append(nav.state.path)
        assert paths == [(), ('main',), ('main', 'settings'), ('main',), ()]
