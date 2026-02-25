"""Shared view computation helpers.

This module provides utility functions for view computation that are used
by both view_computation.py and view_renderer.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.view_registry import get_menu_id_for_path

if TYPE_CHECKING:
    from ubo_app.store.core.types import DynamicMenusState, MainState


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


def find_dynamic_menu_for_position(
    main_state: MainState,
    dynamic_menus_state: DynamicMenusState | None,
    stack: tuple,
) -> tuple[str, str] | None:
    """Find a dynamic menu matching the current navigation position.

    Uses path-based mapping to find the dynamic menu for the current position.

    Args:
        main_state: The main state containing navigation path.
        dynamic_menus_state: The dynamic menus state.
        stack: The navigation stack (unused, kept for API compatibility).

    Returns:
        Tuple of (menu_id, title) if found, None otherwise.

    """
    if not dynamic_menus_state:
        return None

    # Path-based mapping
    menu_id = get_dynamic_menu_id_for_stack(main_state)
    if menu_id:
        dynamic_menu = dynamic_menus_state.menus.get(menu_id)
        if dynamic_menu:
            return (menu_id, dynamic_menu.title)

    return None
