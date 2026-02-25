"""Adapter between Redux-native types and ubo-gui Menu types.

This module provides functions to convert between ubo-gui's Menu/Item types
and the Redux-native MenuItemData types. This decouples the core store from
ubo-gui dependencies and enables serialization.

NOTE: item_to_menu_item_data is still needed for converting notification
actions (ubo_gui types) to MenuItemData. Other functions have been removed
as part of the legacy menu tree removal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_gui.menu.types import SubMenuItem

from ubo_app.store.core.types import MenuItemData

if TYPE_CHECKING:
    from ubo_gui.menu.types import Item


def item_to_menu_item_data(
    item: Item | None,
    index: int,
) -> MenuItemData | None:
    """Convert a ubo_gui Item to a MenuItemData for rendering.

    Returns None if the input item is None (placeholder slot).

    Args:
        item: The ubo-gui Item to convert.
        index: Index of the item in the menu.

    Returns:
        MenuItemData representation, or None if item is None.

    """
    if item is None:
        return None

    # Determine action_id based on item type.
    # Only SubMenuItems get menu:select: -- these trigger StackPushMenuAction.
    # ActionItems must NOT get menu:select: because pushing them onto the stack
    # causes find_menu_for_item to call action() on every autorun cycle,
    # triggering repeated side effects (e.g. notification floods).
    action_id: str | None = None
    key_val = getattr(item, 'key', None)
    if key_val and isinstance(key_val, str) and isinstance(item, SubMenuItem):
        action_id = f'menu:select:{key_val}'

    # Get values with safe defaults, handling callables
    key: str = f'item_{index}'
    if key_val:
        key = key_val if isinstance(key_val, str) else f'item_{index}'

    label_val = getattr(item, 'label', '')
    label = label_val() if callable(label_val) else (label_val or '')

    icon_val = getattr(item, 'icon', '')
    icon = icon_val() if callable(icon_val) else (icon_val or '')

    # Handle background_color
    bg_color_val = getattr(item, 'background_color', None)
    bg_color: str | None = None
    if isinstance(bg_color_val, str):
        bg_color = bg_color_val

    # Handle icon_color
    icon_color = '#ffffff'
    icon_color_val = getattr(item, 'icon_color', None)
    if icon_color_val:
        if callable(icon_color_val):
            resolved = icon_color_val()
            if isinstance(resolved, str):
                icon_color = resolved
        elif isinstance(icon_color_val, str):
            icon_color = icon_color_val

    # Handle is_short - could be bool or callable
    is_short_val = getattr(item, 'is_short', False)
    is_short = is_short_val if isinstance(is_short_val, bool) else False

    return MenuItemData(
        key=key,
        label=str(label),
        icon=str(icon),
        color=icon_color,
        is_short=is_short,
        background_color=bg_color,
        action_id=action_id,
    )
