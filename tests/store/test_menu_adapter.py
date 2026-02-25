"""Tests for menu_adapter.py functions.

Tests conversion between ubo-gui types and Redux-native MenuItemData.
"""

from __future__ import annotations

from ubo_gui.menu.types import ActionItem, HeadlessMenu, SubMenuItem

from ubo_app.store.core.menu_adapter import item_to_menu_item_data
from ubo_app.store.core.types import MenuItemData


# Test menus
LEAF_MENU = HeadlessMenu(title='Leaf', items=[], placeholder='Empty')


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
        item = ActionItem(
            key='reboot', label='Reboot', icon='R', action=lambda: None,
        )
        result = item_to_menu_item_data(item, 1)
        assert result is not None
        assert result.key == 'reboot'
        assert result.label == 'Reboot'
        assert result.action_id is None  # ActionItems don't get menu:select:

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
