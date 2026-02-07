"""Tests for pagination (page index management).

Tests StackSetPageIndexAction and its effect on views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    HomeViewData,
    MenuViewData,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackSetPageIndexAction,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner


class TestSetPageIndex:
    """Tests for setting page index on menus."""

    def test_set_page_index(self, nav: ReducerRunner) -> None:
        """Verify setting page index updates the view's page_index."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackSetPageIndexAction(page_index=1))
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.page_index == 1

    def test_page_index_zero_by_default(self, nav: ReducerRunner) -> None:
        """Verify a newly pushed menu starts at page index zero."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.page_index == 0

    def test_set_page_index_on_non_menu_is_noop(self, nav: ReducerRunner) -> None:
        """Verify setting page index on an application stack item is a no-op."""
        nav.dispatch(StackPushApplicationAction(application_id='test:app'))
        original_stack = nav.state.stack
        nav.dispatch(StackSetPageIndexAction(page_index=1))
        assert nav.state.stack == original_stack

    def test_set_page_index_at_root(self, nav: ReducerRunner) -> None:
        """At root, top is MenuStackItem so page index can be set."""
        nav.dispatch(StackSetPageIndexAction(page_index=1))
        # Root is a MenuStackItem so this should succeed
        view = nav.view
        assert isinstance(view, HomeViewData)


class TestStatusBarVisibility:
    """Tests for status bar based on page index."""

    def test_first_page_shows_status_bar(self, nav: ReducerRunner) -> None:
        """Verify the status bar is visible on the first page."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.show_status_bar is True

    def test_later_page_hides_status_bar(self, nav: ReducerRunner) -> None:
        """Verify the status bar is hidden on pages after the first."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackSetPageIndexAction(page_index=1))
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.show_status_bar is False

    def test_back_to_first_page_shows_status_bar(self, nav: ReducerRunner) -> None:
        """Verify the status bar reappears when returning to page zero."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackSetPageIndexAction(page_index=1))
        nav.dispatch(StackSetPageIndexAction(page_index=0))
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.show_status_bar is True


class TestTotalPages:
    """Tests for total_pages computation."""

    def test_total_pages_for_main_menu(self, nav: ReducerRunner) -> None:
        """Main menu has 2 items, PAGE_SIZE=3, so 1 page."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.total_pages == 1

    def test_total_pages_for_settings(self, nav: ReducerRunner) -> None:
        """Settings menu has 2 items, so 1 page."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.total_pages == 1

    def test_home_view_has_correct_items(self, nav: ReducerRunner) -> None:
        """Home view should have all 3 items."""
        view = nav.view
        assert isinstance(view, HomeViewData)
        assert len(view.menu_items) == 3
