"""Shared view computation helpers.

This module provides utility functions for view computation that are used
by both view_computation.py and view_renderer.py, eliminating duplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.constants import NERD_FONT_ICON_CHARS
from ubo_app.store.core.menu_adapter import get_current_menu_from_stack
from ubo_app.store.core.view_registry import get_menu_id_for_path

if TYPE_CHECKING:
    from ubo_app.store.core.types import DynamicMenusState, MainState


def strip_nerd_font_icons(text: str) -> str:
    """Strip nerd font icon characters from the beginning of text.

    Args:
        text: Text that may start with nerd font icons.

    Returns:
        Text with leading icons removed and whitespace stripped.

    """
    return text.lstrip(NERD_FONT_ICON_CHARS).strip()


def normalize_menu_title(title: str) -> str:
    """Normalize a menu title for comparison.

    Strips nerd font icons and whitespace to enable title matching
    regardless of icon prefixes.

    Args:
        title: The menu title to normalize.

    Returns:
        Normalized title string.

    """
    return strip_nerd_font_icons(title)


def get_dynamic_menu_id_for_stack(main_state: MainState) -> str | None:
    """Determine which dynamic menu ID corresponds to the current stack position.

    This maps the navigation path to a dynamic menu ID. Services register their
    path matchers via register_path_menu_matcher() in view_registry.py.

    Args:
        main_state: The main state containing navigation path.

    Returns:
        Dynamic menu ID if a registered matcher matches, None otherwise.

    """
    # Use reactive path from state (computed by reducer)
    path = main_state.path
    if not path:
        return None

    # Use registered path matchers (services register their own)
    return get_menu_id_for_path(path)


def find_dynamic_menu_by_title(
    title: str,
    dynamic_menus_state: DynamicMenusState,
) -> str | None:
    """Find a dynamic menu ID by matching the menu title.

    This is used when path-based mapping fails, as some menus are
    returned by action callbacks and don't appear in the navigation path.

    Args:
        title: The menu title to search for.
        dynamic_menus_state: The dynamic menus state.

    Returns:
        The menu_id if found, None otherwise.

    """
    # Normalize title for comparison (some titles have icon prefixes)
    clean_title = normalize_menu_title(title)

    for menu_id, menu_data in dynamic_menus_state.menus.items():
        menu_title = normalize_menu_title(menu_data.title)
        if clean_title == menu_title:
            return menu_id

    return None


def find_dynamic_menu_for_position(
    main_state: MainState,
    dynamic_menus_state: DynamicMenusState | None,
    stack: tuple,
) -> tuple[str, str] | None:
    """Find a dynamic menu matching the current navigation position.

    Tries path-based mapping first, then falls back to title-based matching.

    Args:
        main_state: The main state containing navigation path.
        dynamic_menus_state: The dynamic menus state.
        stack: The navigation stack.

    Returns:
        Tuple of (menu_id, title) if found, None otherwise.

    """
    if not dynamic_menus_state:
        return None

    # Try path-based mapping first
    menu_id = get_dynamic_menu_id_for_stack(main_state)
    if menu_id:
        dynamic_menu = dynamic_menus_state.menus.get(menu_id)
        if dynamic_menu:
            return (menu_id, dynamic_menu.title)

    # Fall back to title-based matching
    if not dynamic_menus_state.menus:
        return None

    current_menu = get_current_menu_from_stack(main_state.menu, stack)
    if current_menu is None:
        return None

    title_val = current_menu.title
    current_title = str(title_val() if callable(title_val) else (title_val or ''))
    if not current_title:
        return None

    found_menu_id = find_dynamic_menu_by_title(current_title, dynamic_menus_state)
    if found_menu_id:
        dynamic_menu = dynamic_menus_state.menus.get(found_menu_id)
        if dynamic_menu:
            return (found_menu_id, dynamic_menu.title)

    return None
