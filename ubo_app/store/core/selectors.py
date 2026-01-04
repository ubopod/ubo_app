# ruff: noqa: D100, D103
"""Computed selectors for navigation state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_gui.menu.constants import PAGE_SIZE
from ubo_gui.menu.types import Menu, SubMenuItem, menu_items

from ubo_app.store.core.types import (
    ApplicationStackItem,
    MenuStackItem,
    StackItem,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item

    from ubo_app.store.main import RootState


def select_navigation_stack(state: RootState) -> tuple[StackItem, ...]:
    """Get the navigation stack."""
    return state.main.navigation_stack


def select_stack_depth(state: RootState) -> int:
    """Get current stack depth."""
    return len(state.main.navigation_stack)


def select_is_at_home(state: RootState) -> bool:
    """Check if at root menu (empty stack)."""
    return len(state.main.navigation_stack) == 0


def select_top_stack_item(state: RootState) -> StackItem | None:
    """Get the top item of navigation stack."""
    if not state.main.navigation_stack:
        return None
    return state.main.navigation_stack[-1]


def select_current_menu_path(state: RootState) -> tuple[str, ...]:
    """Get the current menu path from the top MenuStackItem."""
    if not state.main.navigation_stack:
        return ()
    top = state.main.navigation_stack[-1]
    if isinstance(top, MenuStackItem):
        return top.menu_path
    # If top is an application, find the last menu in stack
    for item in reversed(state.main.navigation_stack):
        if isinstance(item, MenuStackItem):
            return item.menu_path
    return ()


def select_current_page_index(state: RootState) -> int:
    """Get page_index of current menu, or 0."""
    if not state.main.navigation_stack:
        return 0
    top = state.main.navigation_stack[-1]
    if isinstance(top, MenuStackItem):
        return top.page_index
    return 0


def _traverse_menu_path(root_menu: Menu | None, path: tuple[str, ...]) -> Menu | None:
    """Traverse the menu tree following the given path of keys."""
    if root_menu is None:
        return None

    current_menu = root_menu
    for key in path:
        items = menu_items(current_menu)
        found = False
        for item in items:
            if item.key == key and isinstance(item, SubMenuItem):
                sub = item.sub_menu
                if callable(sub):
                    sub = sub()
                if isinstance(sub, Menu):
                    current_menu = sub
                    found = True
                    break
        if not found:
            return None
    return current_menu


def select_current_menu(state: RootState) -> Menu | None:
    """Traverse menu tree based on navigation_stack to get current menu."""
    path = select_current_menu_path(state)
    return _traverse_menu_path(state.main.menu, path)


def select_current_menu_items(state: RootState) -> Sequence[Item]:
    """Get all items for the current menu."""
    current_menu = select_current_menu(state)
    if current_menu is None:
        return []
    return menu_items(current_menu)


def select_current_items(state: RootState) -> Sequence[Item | None]:
    """Get items for current page, respecting page_index and PAGE_SIZE."""
    all_items = select_current_menu_items(state)
    page_index = select_current_page_index(state)

    start = page_index * PAGE_SIZE
    end = start + PAGE_SIZE

    # Pad with None if needed
    page_items: list[Item | None] = list(all_items[start:end])
    while len(page_items) < PAGE_SIZE:
        page_items.append(None)

    return page_items


def select_total_pages(state: RootState) -> int:
    """Calculate total pages for current menu."""
    all_items = select_current_menu_items(state)
    if not all_items:
        return 1
    return max(1, (len(all_items) + PAGE_SIZE - 1) // PAGE_SIZE)


def select_breadcrumb(state: RootState) -> tuple[str, ...]:
    """Get tuple of titles for breadcrumb display."""
    titles: list[str] = []
    for item in state.main.navigation_stack:
        if isinstance(item, MenuStackItem | ApplicationStackItem):
            if item.title:
                titles.append(item.title)
            elif item.key:
                titles.append(item.key)
    return tuple(titles)


def select_can_go_up(state: RootState) -> bool:
    """Check if can scroll up (previous page exists)."""
    return select_current_page_index(state) > 0


def select_can_go_down(state: RootState) -> bool:
    """Check if can scroll down (next page exists)."""
    return select_current_page_index(state) < select_total_pages(state) - 1


def select_current_title(state: RootState) -> str:
    """Get the title of the current view."""
    top = select_top_stack_item(state)
    if top is None:
        # At home, use root menu title if available
        if state.main.menu:
            return getattr(state.main.menu, 'title', '') or ''
        return ''
    return top.title or ''
