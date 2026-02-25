"""Bridge for converting legacy ubo_gui Item sequences to dynamic menus.

Services that still use ubo_gui types (ActionItem, SubMenuItem, UboDispatchItem)
in their autoruns can use this bridge to convert them to dynamic menus with
serializable MenuItemData and registered action handlers.

Usage in a service autorun:

    from ubo_app.store.core.menu_item_bridge import sync_items_to_dynamic_menu

    @store.autorun(lambda state: state.my_service.some_data)
    def update_menu(data):
        items = [ActionItem(key='foo', label='Foo', action=do_foo), ...]
        sync_items_to_dynamic_menu(
            menu_id='my-service:main',
            title='My Service',
            items=items,
        )
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_gui.menu.types import SubMenuItem  # pyright: ignore[reportMissingImports]

from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import MenuItemData, UpdateDynamicMenuAction
from ubo_app.store.main import store

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_gui.menu.types import Item  # pyright: ignore[reportMissingImports]


# Track registered action_ids per menu_id so we can clean up on re-sync
_menu_action_ids: dict[str, list[str]] = {}


def sync_items_to_dynamic_menu(  # noqa: PLR0913
    *,
    menu_id: str,
    title: str,
    items: Sequence[Item | None],
    placeholder: str = '',
    heading: str | None = None,
    sub_heading: str | None = None,
) -> None:
    """Convert a sequence of ubo_gui Items to a dynamic menu."""
    # Clean up previously registered actions for this menu
    _cleanup_menu_actions(menu_id)

    # Convert items
    menu_items: list[MenuItemData | None] = []
    action_ids: list[str] = []

    for i, item in enumerate(items):
        if item is None:
            menu_items.append(None)
            continue

        menu_item_data, registered_ids = _convert_item(item, i, menu_id)
        menu_items.append(menu_item_data)
        action_ids.extend(registered_ids)

    _menu_action_ids[menu_id] = action_ids

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=menu_id,
            title=title,
            items=tuple(menu_items),
            placeholder=placeholder,
            heading=heading,
            sub_heading=sub_heading,
        ),
    )


def _cleanup_menu_actions(menu_id: str) -> None:
    """Unregister all action handlers previously registered for a menu."""
    old_ids = _menu_action_ids.pop(menu_id, [])
    for action_id in old_ids:
        unregister_action(action_id)


def _extract_item_fields(item: Item, index: int) -> dict[str, object]:
    """Extract common serializable fields from a ubo_gui Item."""
    key_val = getattr(item, 'key', None)
    key = key_val if isinstance(key_val, str) else f'item_{index}'

    label_val = getattr(item, 'label', '')
    label = label_val() if callable(label_val) else (label_val or '')

    icon_val = getattr(item, 'icon', '')
    icon = icon_val() if callable(icon_val) else (icon_val or '')

    bg_color_val = getattr(item, 'background_color', None)
    bg_color: str | None = bg_color_val if isinstance(bg_color_val, str) else None

    icon_color = _resolve_icon_color(getattr(item, 'icon_color', None))

    is_short_val = getattr(item, 'is_short', False)
    is_short = is_short_val if isinstance(is_short_val, bool) else False

    return {
        'key': key,
        'label': str(label),
        'icon': str(icon),
        'background_color': bg_color,
        'color': icon_color,
        'is_short': is_short,
    }


def _resolve_icon_color(icon_color_val: object) -> str:
    """Resolve an icon_color field that may be a callable or string."""
    if callable(icon_color_val):
        resolved = icon_color_val()
        return resolved if isinstance(resolved, str) else '#ffffff'
    if isinstance(icon_color_val, str):
        return icon_color_val
    return '#ffffff'


def _create_submenu_dynamic_menu(
    key: str,
    sub_menu: object,
    parent_menu_id: str,
    registered_ids: list[str],
) -> None:
    """Create a dynamic menu for a SubMenuItem's sub_menu.

    This resolves the sub_menu's items and title, then dispatches
    sync_items_to_dynamic_menu to create a dynamic menu accessible
    when the user navigates into the SubMenuItem.
    """
    title_raw = getattr(sub_menu, 'title', key)
    title = title_raw() if callable(title_raw) else (title_raw or key)

    items_raw = getattr(sub_menu, 'items', [])
    items_resolved = items_raw() if callable(items_raw) else items_raw
    items_list: list[Item] = (
        list(items_resolved)  # pyright: ignore[reportArgumentType]
        if items_resolved
        else []
    )

    heading_raw = getattr(sub_menu, 'heading', None)
    heading = heading_raw() if callable(heading_raw) else heading_raw

    sub_heading_raw = getattr(sub_menu, 'sub_heading', None)
    sub_heading = (
        sub_heading_raw() if callable(sub_heading_raw) else sub_heading_raw
    )

    placeholder_raw = getattr(sub_menu, 'placeholder', '')
    placeholder = (
        placeholder_raw() if callable(placeholder_raw) else placeholder_raw
    )

    # Use a child menu_id derived from parent
    child_menu_id = f'{parent_menu_id}:{key}'

    # Convert sub-menu items and dispatch dynamic menu
    child_items: list[MenuItemData | None] = []
    for i, child_item in enumerate(items_list):
        if child_item is None:
            child_items.append(None)
            continue
        child_data, child_ids = _convert_item(child_item, i, child_menu_id)
        child_items.append(child_data)
        registered_ids.extend(child_ids)

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=child_menu_id,
            title=str(title),
            heading=str(heading) if heading else None,
            sub_heading=str(sub_heading) if sub_heading else None,
            items=tuple(child_items),
            placeholder=str(placeholder) if placeholder else '',
        ),
    )


def _convert_item(
    item: Item,
    index: int,
    menu_id: str,
) -> tuple[MenuItemData, list[str]]:
    """Convert a single ubo_gui Item to MenuItemData.

    Returns:
        Tuple of (MenuItemData, list of registered action_ids).

    """
    from ubo_gui.menu.types import ActionItem  # pyright: ignore[reportMissingImports]

    registered_ids: list[str] = []
    fields = _extract_item_fields(item, index)
    key = fields['key']

    # Determine action_id based on item type
    action_id: str | None = None

    if isinstance(item, SubMenuItem):
        key_val = getattr(item, 'key', None)
        if key_val and isinstance(key_val, str):
            action_id = f'menu:select:{key_val}'
            # Recursively create dynamic menu for the sub_menu
            sub_menu = getattr(item, 'sub_menu', None)
            if sub_menu is not None:
                _create_submenu_dynamic_menu(
                    key_val,
                    sub_menu,
                    menu_id,
                    registered_ids,
                )
    elif isinstance(item, ActionItem):
        action_id = f'{menu_id}:{key}'
        action_handler = _make_action_handler(item)
        if action_handler:
            try:
                register_action(action_id, action_handler)
                registered_ids.append(action_id)
            except ValueError:
                logger.debug(
                    'Action %s already registered, skipping',
                    action_id,
                )

    return (
        MenuItemData(
            key=str(key),
            label=str(fields['label']),
            icon=str(fields['icon']),
            color=str(fields['color']),
            is_short=bool(fields['is_short']),
            background_color=fields['background_color']
            if isinstance(fields['background_color'], str)
            else None,
            action_id=action_id,
        ),
        registered_ids,
    )


def _make_action_handler(
    item: Item,
) -> Callable[[], object] | None:
    """Create an action handler for an ActionItem or UboDispatchItem."""
    from ubo_gui.menu.types import ActionItem  # pyright: ignore[reportMissingImports]

    from ubo_app.store.ubo_actions import UboDispatchItem

    if isinstance(item, UboDispatchItem):
        store_action = item.store_action

        def _dispatch_handler() -> None:
            if isinstance(store_action, list):
                store.dispatch(*store_action)
            else:
                store.dispatch(store_action)

        return _dispatch_handler

    if isinstance(item, ActionItem) and item.action:
        action_callable = item.action

        def _action_handler() -> object:
            return action_callable()

        return _action_handler

    return None
