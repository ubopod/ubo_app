"""Adapter between Redux-native types and ubo-gui Menu types.

This module provides functions to convert between ubo-gui's Menu/Item types
and the Redux-native MenuItemData types. This decouples the core store from
ubo-gui dependencies and enables serialization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_gui.menu.types import ActionItem, SubMenuItem, menu_items

from ubo_app.logger import logger
from ubo_app.store.core.types import MenuItemData, MenuStackItem

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item, Menu

    from ubo_app.store.core.types import StackItemType


def find_sub_menu_item(items: Sequence[Item], key: str) -> SubMenuItem:
    """Find a SubMenuItem in the items by key.

    Args:
        items: Sequence of menu items to search.
        key: Key of the item to find.

    Returns:
        The SubMenuItem with the matching key.

    Raises:
        TypeError: If the item is not found or is not a SubMenuItem.

    """
    item = next((item for item in items if item.key == key), None)
    if not isinstance(item, SubMenuItem):
        msg = f'{key.capitalize()} menu item is not a `SubMenuItem`'
        raise TypeError(msg)
    return item


def find_menu_for_item(items: Sequence[Item], key: str) -> Menu | None:
    """Find the menu for an item by key.

    Handles both SubMenuItem (with sub_menu) and ActionItem (with action that
    returns a menu or a callable that returns a menu). Returns None if no menu
    can be found.

    Args:
        items: Sequence of menu items to search.
        key: Key of the item to find.

    Returns:
        The Menu associated with the item, or None if not found.

    """
    item = next((item for item in items if item.key == key), None)
    if item is None:
        logger.debug('[MenuAdapter] find_menu_for_item: no item with key=%s', key)
        return None

    logger.debug(
        '[MenuAdapter] find_menu_for_item: key=%s, item_type=%s',
        key,
        type(item).__name__,
    )

    # Handle SubMenuItem - has sub_menu attribute
    if isinstance(item, SubMenuItem):
        sub_menu = item.sub_menu
        logger.debug(
            '[MenuAdapter] find_menu_for_item: SubMenuItem sub_menu is %s',
            'callable' if callable(sub_menu) else type(sub_menu).__name__,
        )
        try:
            result = sub_menu() if callable(sub_menu) else sub_menu
        except Exception:
            logger.exception(
                '[MenuAdapter] find_menu_for_item: sub_menu() raised exception '
                'for key=%s',
                key,
            )
            return None
        logger.debug(
            '[MenuAdapter] find_menu_for_item: sub_menu resolved to %s',
            type(result).__name__ if result else 'None',
        )
        return result

    # Handle ActionItem - action may return a menu or callable that returns menu
    if isinstance(item, ActionItem) and item.action:
        try:
            logger.debug('[MenuAdapter] find_menu_for_item: calling ActionItem.action()')
            result = item.action()
            logger.debug(
                '[MenuAdapter] find_menu_for_item: action() returned %s',
                type(result).__name__ if result else 'None',
            )
            # If result is callable (e.g., autorun wrapper), call it to get menu
            if callable(result):
                result = result()
                logger.debug(
                    '[MenuAdapter] find_menu_for_item: callable result resolved to %s',
                    type(result).__name__ if result else 'None',
                )
            # Check if result is a Menu (HeadedMenu, HeadlessMenu, etc.)
            if hasattr(result, 'items') and hasattr(result, 'title'):
                return result
        except Exception:
            logger.exception(
                '[MenuAdapter] find_menu_for_item: action() raised exception',
            )

    return None


def get_menu_items(menu: Menu) -> Sequence[Item]:
    """Get the items from a menu, resolving callables if needed.

    Args:
        menu: The menu to get items from.

    Returns:
        Sequence of menu items.

    """
    return menu_items(menu)


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

    # Determine action_id based on item type
    action_id: str | None = None
    key_val = getattr(item, 'key', None)
    if key_val and isinstance(key_val, str):
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


def menu_to_menu_data(menu: Menu | None) -> tuple[MenuItemData | None, ...]:
    """Convert a ubo-gui Menu to a tuple of MenuItemData.

    Args:
        menu: The menu to convert.

    Returns:
        Tuple of MenuItemData representing the menu items.

    """
    if menu is None:
        return ()
    items = menu_items(menu)
    return tuple(item_to_menu_item_data(item, i) for i, item in enumerate(items))


def get_current_menu_from_stack(
    root_menu: Menu | None,
    stack: tuple[StackItemType, ...],
) -> Menu | None:
    """Traverse menu tree based on stack to get current menu.

    This follows the stack path to find the menu currently at the top.
    Only works when the top of stack is a MenuStackItem.

    Args:
        root_menu: The root menu to start traversal from.
        stack: The navigation stack.

    Returns:
        The current menu, or None if not found.

    """
    if not root_menu or not stack:
        return None

    # Only consider MenuStackItems for menu traversal
    menu_path = [item for item in stack if isinstance(item, MenuStackItem)]
    if not menu_path:
        return None

    current_menu: Menu | None = root_menu
    for item in menu_path[1:]:  # Skip root
        if current_menu is None:
            return None
        logger.debug(
            '[MenuAdapter] traversing to key=%s',
            item.menu_key,
        )
        items = menu_items(current_menu)
        # Use find_menu_for_item which handles both SubMenuItem and ActionItem
        current_menu = find_menu_for_item(items, item.menu_key)
        if current_menu is None:
            logger.debug(
                '[MenuAdapter] traversal stopped: no menu for key=%s',
                item.menu_key,
            )
            return None
    logger.debug(
        '[MenuAdapter] traversal complete: menu=%s',
        type(current_menu).__name__ if current_menu else 'None',
    )
    return current_menu
