"""Tests for keypad-driven navigation and scroll sync.

Simulates the full flow a GUI client would see via gRPC:
  L1 (enter Main) → L1 (enter Apps) → DOWN (scroll) → DOWN (scroll again)

Asserts on ViewData at each step to verify page_index and total_pages stay
in sync, which is what the GUI client receives and renders.

The core sends ALL items in the MenuViewData; the GUI client uses page_index
and PAGE_SIZE to determine which slice to display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_gui.menu.types import SubMenuItem, menu_items  # pyright: ignore[reportMissingImports]

from ubo_app.store.core.constants import PAGE_SIZE
from ubo_app.store.core.menu_adapter import get_current_menu_from_stack
from ubo_app.store.core.types import (
    HomeViewData,
    MenuScrollDirection,
    MenuStackItem,
    MenuViewData,
    StackPushMenuAction,
    StackSetPageIndexAction,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner


def _choose_by_index(nav: ReducerRunner, index: int) -> None:
    """Simulate what menu_event_handlers._handle_choose_by_index does.

    Looks up the item at the given visual index (accounting for page_index),
    and dispatches the corresponding StackPushMenuAction.
    """
    state = nav.state
    stack = state.stack
    menu = state.menu

    current_menu = get_current_menu_from_stack(menu, stack)
    assert current_menu is not None, 'No current menu'
    items = list(menu_items(current_menu))

    top = stack[-1]
    page_index = top.page_index if isinstance(top, MenuStackItem) else 0
    actual_index = page_index * PAGE_SIZE + index

    assert actual_index < len(items), (
        f'Index {actual_index} out of range (have {len(items)} items)'
    )

    item = items[actual_index]
    assert isinstance(item, SubMenuItem), f'Expected SubMenuItem, got {type(item)}'
    assert item.key is not None
    nav.dispatch(StackPushMenuAction(menu_key=item.key))


def _scroll(nav: ReducerRunner, direction: MenuScrollDirection) -> None:
    """Simulate what menu_event_handlers._handle_scroll does.

    Computes the new page index from the current page and dispatches
    StackSetPageIndexAction.
    """
    state = nav.state
    stack = state.stack
    top = stack[-1]
    assert isinstance(top, MenuStackItem), 'Top is not a MenuStackItem'

    menu = state.menu
    current_menu = get_current_menu_from_stack(menu, stack)
    assert current_menu is not None
    items = list(menu_items(current_menu))

    total_pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page_index = top.page_index

    if direction == MenuScrollDirection.UP:
        new_page = (page_index - 1) % total_pages
    else:
        new_page = (page_index + 1) % total_pages

    if new_page != page_index:
        nav.dispatch(StackSetPageIndexAction(page_index=new_page))


def _items_for_page(
    all_items: tuple[object, ...],
    page_index: int,
) -> list[str]:
    """Return labels for the given page slice (what the GUI client shows)."""
    start = page_index * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(all_items))
    return [
        item.label
        for item in all_items[start:end]
        if item is not None and hasattr(item, 'label')
    ]


class TestKeypadNavigationFlow:
    """Tests simulating keypad-driven navigation: L1→L1→DOWN→DOWN.

    Each step mirrors what the headless menu_event_handlers do when
    receiving KeypadKeyPressAction events, and asserts on the ViewData
    that the GUI client would receive via gRPC.
    """

    def test_initial_home_view(self, nav: ReducerRunner) -> None:
        """Verify we start at the home screen with 3 menu items."""
        view = nav.view
        assert isinstance(view, HomeViewData)
        labels = [item.label for item in view.menu_items]
        assert labels == ['Main', 'Notifications', 'Power']

    def test_l1_enters_main_menu(self, nav: ReducerRunner) -> None:
        """L1 selects item 0 (Main) from the home screen."""
        _choose_by_index(nav, 0)

        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.title == 'Main'
        assert view.page_index == 0
        labels = [item.label for item in view.items if item is not None]
        assert 'Apps' in labels
        assert 'Settings' in labels

    def test_l1_l1_enters_apps(self, nav: ReducerRunner) -> None:
        """L1→L1 navigates Main → Apps."""
        _choose_by_index(nav, 0)  # → Main
        _choose_by_index(nav, 0)  # → Apps (first item in Main)

        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.title == 'Apps'
        assert view.page_index == 0
        assert view.total_pages == 3  # 7 items / PAGE_SIZE=3 → ceil = 3

        # All 7 items are present in the view
        labels = [item.label for item in view.items if item is not None]
        assert len(labels) == 7

    def test_full_flow_l1_l1_down_down(self, nav: ReducerRunner) -> None:
        """Full L1→L1→DOWN→DOWN flow with data assertions at each step."""
        # Step 1: L1 → enter Main
        _choose_by_index(nav, 0)
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.title == 'Main'

        # Step 2: L1 → enter Apps
        _choose_by_index(nav, 0)
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.title == 'Apps'
        assert view.page_index == 0
        assert view.total_pages == 3

        # GUI client would show these items for page 0
        page0_labels = _items_for_page(view.items, view.page_index)
        assert page0_labels == ['App 0', 'App 1', 'App 2']

        # Step 3: DOWN → scroll to page 1
        _scroll(nav, MenuScrollDirection.DOWN)
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.title == 'Apps'
        assert view.page_index == 1
        assert view.total_pages == 3

        # GUI client would show these items for page 1
        page1_labels = _items_for_page(view.items, view.page_index)
        assert page1_labels == ['App 3', 'App 4', 'App 5']

        # Step 4: DOWN → scroll to page 2
        _scroll(nav, MenuScrollDirection.DOWN)
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.title == 'Apps'
        assert view.page_index == 2
        assert view.total_pages == 3

        # GUI client would show these items for page 2 (partial page)
        page2_labels = _items_for_page(view.items, view.page_index)
        assert page2_labels == ['App 6']


class TestScrollSync:
    """Tests that page_index and displayed items stay in sync.

    These verify the invariant that the GUI client can trust:
    items_for_page(view.items, view.page_index) always shows the correct
    slice.
    """

    def test_page_index_matches_items_slice(self, nav: ReducerRunner) -> None:
        """Verify items match the page_index slice for every page."""
        _choose_by_index(nav, 0)  # → Main
        _choose_by_index(nav, 0)  # → Apps (7 items, 3 pages)

        all_labels = [f'App {i}' for i in range(7)]

        for page in range(3):
            if page > 0:
                _scroll(nav, MenuScrollDirection.DOWN)

            view = nav.view
            assert isinstance(view, MenuViewData)
            assert view.page_index == page

            start = page * PAGE_SIZE
            end = min(start + PAGE_SIZE, len(all_labels))
            expected = all_labels[start:end]
            actual = _items_for_page(view.items, view.page_index)
            assert actual == expected, (
                f'Page {page}: expected {expected}, got {actual}'
            )

    def test_scroll_wraps_around(self, nav: ReducerRunner) -> None:
        """Verify scrolling past the last page wraps to the first."""
        _choose_by_index(nav, 0)  # → Main
        _choose_by_index(nav, 0)  # → Apps

        # Scroll through all pages and wrap
        _scroll(nav, MenuScrollDirection.DOWN)  # page 1
        _scroll(nav, MenuScrollDirection.DOWN)  # page 2
        _scroll(nav, MenuScrollDirection.DOWN)  # wraps to page 0

        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.page_index == 0
        labels = _items_for_page(view.items, view.page_index)
        assert labels == ['App 0', 'App 1', 'App 2']

    def test_scroll_up_wraps_around(self, nav: ReducerRunner) -> None:
        """Verify scrolling up from page 0 wraps to the last page."""
        _choose_by_index(nav, 0)  # → Main
        _choose_by_index(nav, 0)  # → Apps

        _scroll(nav, MenuScrollDirection.UP)  # wraps to last page

        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.page_index == 2  # last page
        labels = _items_for_page(view.items, view.page_index)
        assert labels == ['App 6']

    def test_status_bar_hidden_on_later_pages(self, nav: ReducerRunner) -> None:
        """Verify status bar is visible on page 0, hidden on later pages."""
        _choose_by_index(nav, 0)  # → Main
        _choose_by_index(nav, 0)  # → Apps

        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.show_status_bar is True  # page 0

        _scroll(nav, MenuScrollDirection.DOWN)
        view = nav.view
        assert isinstance(view, MenuViewData)
        assert view.show_status_bar is False  # page 1

    def test_events_emitted_on_scroll(self, nav: ReducerRunner) -> None:
        """Verify the reducer emits correct events during scroll."""
        _choose_by_index(nav, 0)  # → Main
        _choose_by_index(nav, 0)  # → Apps
        nav.clear_events()

        _scroll(nav, MenuScrollDirection.DOWN)

        from ubo_app.store.core.types import (
            StackPageIndexChangedEvent,
            ViewChangedEvent,
        )

        page_events = [
            e for e in nav.last_events if isinstance(e, StackPageIndexChangedEvent)
        ]
        view_events = [
            e for e in nav.last_events if isinstance(e, ViewChangedEvent)
        ]
        assert len(page_events) == 1
        assert page_events[0].page_index == 1
        assert len(view_events) == 1
