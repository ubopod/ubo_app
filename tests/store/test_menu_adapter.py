"""Tests for menu_adapter.py functions.

Tests conversion between ubo-gui types and Redux-native MenuItemData.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from ubo_gui.menu.types import ActionItem, HeadlessMenu, Item, SubMenuItem

from ubo_app.store.core.menu_adapter import (
    find_menu_for_item,
    find_sub_menu_item,
    get_current_menu_from_stack,
    item_to_menu_item_data,
    menu_to_menu_data,
)
from ubo_app.store.core.types import (
    ApplicationStackItem,
    MenuItemData,
    MenuStackItem,
    NotificationStackItem,
)

def _resolve_items(menu: HeadlessMenu) -> Sequence[Item]:
    """Resolve menu items, handling callable items."""
    items = menu.items
    if callable(items):
        return items()
    return items


# Test menus
LEAF_MENU = HeadlessMenu(title='Leaf', items=[], placeholder='Empty')

CHILD_MENU = HeadlessMenu(
    title='Child',
    items=[
        SubMenuItem(key='leaf', label='Leaf', icon='L', sub_menu=LEAF_MENU),
    ],
)

ROOT_MENU = HeadlessMenu(
    title='Root',
    items=[
        SubMenuItem(key='child', label='Child', icon='C', sub_menu=CHILD_MENU),
        SubMenuItem(key='other', label='Other', icon='O', sub_menu=LEAF_MENU),
    ],
)


class TestFindSubMenuItem:
    """Tests for find_sub_menu_item."""

    def test_finds_existing_item(self) -> None:
        """Verify find_sub_menu_item locates an item by key."""
        items = list(_resolve_items(ROOT_MENU))
        result = find_sub_menu_item(items, 'child')
        assert isinstance(result, SubMenuItem)
        assert result.key == 'child'

    def test_raises_for_missing_key(self) -> None:
        """Verify find_sub_menu_item raises for a missing key."""
        items = list(_resolve_items(ROOT_MENU))
        with pytest.raises(TypeError, match='Nonexistent'):
            find_sub_menu_item(items, 'nonexistent')

    def test_raises_for_non_submenu_item(self) -> None:
        """Verify find_sub_menu_item raises for a non-SubMenuItem."""
        items = [
            ActionItem(
                key='action', label='Action', icon='A', action=lambda: None,
            ),
        ]
        with pytest.raises(TypeError):
            find_sub_menu_item(items, 'action')


class TestFindMenuForItem:
    """Tests for find_menu_for_item."""

    def test_finds_submenu(self) -> None:
        """Verify find_menu_for_item returns the correct submenu."""
        items = list(_resolve_items(ROOT_MENU))
        result = find_menu_for_item(items, 'child')
        assert result is not None
        assert result.title == 'Child'

    def test_returns_none_for_missing(self) -> None:
        """Verify find_menu_for_item returns None for missing key."""
        items = list(_resolve_items(ROOT_MENU))
        result = find_menu_for_item(items, 'nonexistent')
        assert result is None

    def test_handles_callable_sub_menu(self) -> None:
        """Verify find_menu_for_item resolves callable sub_menu."""
        menu = HeadlessMenu(title='Dynamic', items=[])
        items = [SubMenuItem(key='dyn', label='Dyn', icon='D', sub_menu=lambda: menu)]
        result = find_menu_for_item(items, 'dyn')
        assert result is not None
        assert result.title == 'Dynamic'

    def test_handles_action_item_returning_menu(self) -> None:
        """Verify ActionItem returning a menu is handled correctly."""
        menu = HeadlessMenu(title='FromAction', items=[])
        items = [ActionItem(key='act', label='Act', icon='A', action=lambda: menu)]
        result = find_menu_for_item(items, 'act')
        assert result is not None
        assert result.title == 'FromAction'

    def test_handles_action_item_returning_none(self) -> None:
        """Verify ActionItem returning None yields None result."""
        items = [ActionItem(key='act', label='Act', icon='A', action=lambda: None)]
        result = find_menu_for_item(items, 'act')
        assert result is None


class TestItemToMenuItemData:
    """Tests for item_to_menu_item_data."""

    def test_none_returns_none(self) -> None:
        """Verify None input returns None."""
        result = item_to_menu_item_data(None, 0)
        assert result is None

    def test_submenu_item_conversion(self) -> None:
        """Verify SubMenuItem converts to MenuItemData correctly."""
        item = SubMenuItem(key='wifi', label='Wi-Fi', icon='W', sub_menu=LEAF_MENU)
        result = item_to_menu_item_data(item, 0)
        assert result is not None
        assert isinstance(result, MenuItemData)
        assert result.key == 'wifi'
        assert result.label == 'Wi-Fi'
        assert result.icon == 'W'
        assert result.action_id == 'menu:select:wifi'

    def test_action_item_conversion(self) -> None:
        """Verify ActionItem converts to MenuItemData correctly."""
        item = ActionItem(key='reboot', label='Reboot', icon='R', action=lambda: None)
        result = item_to_menu_item_data(item, 1)
        assert result is not None
        assert result.key == 'reboot'
        assert result.label == 'Reboot'
        assert result.action_id == 'menu:select:reboot'

    def test_callable_label(self) -> None:
        """Verify callable label is resolved to its return value."""
        item = SubMenuItem(
            key='dyn', label=lambda: 'Dynamic Label', icon='D',
            sub_menu=LEAF_MENU,
        )
        result = item_to_menu_item_data(item, 0)
        assert result is not None
        assert result.label == 'Dynamic Label'

    def test_callable_icon(self) -> None:
        """Verify callable icon is resolved to its return value."""
        item = SubMenuItem(
            key='dyn', label='Label', icon=lambda: 'DynIcon',
            sub_menu=LEAF_MENU,
        )
        result = item_to_menu_item_data(item, 0)
        assert result is not None
        assert result.icon == 'DynIcon'

    def test_background_color(self) -> None:
        """Verify background_color is preserved in conversion."""
        item = SubMenuItem(
            key='colored', label='Colored', icon='C',
            background_color='#ff0000', sub_menu=LEAF_MENU,
        )
        result = item_to_menu_item_data(item, 0)
        assert result is not None
        assert result.background_color == '#ff0000'

    def test_default_color_is_white(self) -> None:
        """Verify default text color is white."""
        item = SubMenuItem(key='plain', label='Plain', icon='P', sub_menu=LEAF_MENU)
        result = item_to_menu_item_data(item, 0)
        assert result is not None
        assert result.color == '#ffffff'

    def test_index_used_as_fallback_key(self) -> None:
        """Verify index is used as fallback key when key is None."""
        item = SubMenuItem(key=None, label='NoKey', icon='N', sub_menu=LEAF_MENU)
        result = item_to_menu_item_data(item, 5)
        assert result is not None
        assert result.key == 'item_5'


class TestMenuToMenuData:
    """Tests for menu_to_menu_data."""

    def test_none_returns_empty(self) -> None:
        """Verify None menu returns an empty tuple."""
        assert menu_to_menu_data(None) == ()

    def test_converts_menu_items(self) -> None:
        """Verify menu items are converted to MenuItemData tuple."""
        result = menu_to_menu_data(ROOT_MENU)
        assert len(result) == 2
        assert result[0] is not None
        assert result[0].key == 'child'
        assert result[1] is not None
        assert result[1].key == 'other'

    def test_empty_menu(self) -> None:
        """Verify empty menu returns an empty tuple."""
        menu = HeadlessMenu(title='Empty', items=[])
        result = menu_to_menu_data(menu)
        assert result == ()


class TestGetCurrentMenuFromStack:
    """Tests for get_current_menu_from_stack."""

    def test_root_returns_root_menu(self) -> None:
        """Verify root stack returns the root menu."""
        stack = (MenuStackItem(id='root', menu_key='', page_index=0),)
        result = get_current_menu_from_stack(ROOT_MENU, stack)
        assert result is not None
        assert result.title == 'Root'

    def test_one_level_deep(self) -> None:
        """Verify one-level-deep stack returns the child menu."""
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='c', menu_key='child', page_index=0),
        )
        result = get_current_menu_from_stack(ROOT_MENU, stack)
        assert result is not None
        assert result.title == 'Child'

    def test_two_levels_deep(self) -> None:
        """Verify two-level-deep stack returns the leaf menu."""
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='c', menu_key='child', page_index=0),
            MenuStackItem(id='l', menu_key='leaf', page_index=0),
        )
        result = get_current_menu_from_stack(ROOT_MENU, stack)
        assert result is not None
        assert result.title == 'Leaf'

    def test_nonexistent_key_returns_none(self) -> None:
        """Verify nonexistent menu key returns None."""
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='x', menu_key='nonexistent', page_index=0),
        )
        result = get_current_menu_from_stack(ROOT_MENU, stack)
        assert result is None

    def test_none_root_menu_returns_none(self) -> None:
        """Verify None root menu returns None."""
        stack = (MenuStackItem(id='root', menu_key='', page_index=0),)
        result = get_current_menu_from_stack(None, stack)
        assert result is None

    def test_empty_stack_returns_none(self) -> None:
        """Verify empty stack returns None."""
        result = get_current_menu_from_stack(ROOT_MENU, ())
        assert result is None

    def test_skips_non_menu_items(self) -> None:
        """Verify non-menu stack items are skipped during traversal."""
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            ApplicationStackItem(id='app', application_id='test:app'),
            MenuStackItem(id='c', menu_key='child', page_index=0),
        )
        result = get_current_menu_from_stack(ROOT_MENU, stack)
        assert result is not None
        assert result.title == 'Child'

    def test_ignores_notification_items(self) -> None:
        """Verify notification items are ignored during traversal."""
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='c', menu_key='child', page_index=0),
            NotificationStackItem(id='n', notification_id='n1'),
        )
        result = get_current_menu_from_stack(ROOT_MENU, stack)
        assert result is not None
        assert result.title == 'Child'
