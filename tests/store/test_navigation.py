"""Tests for navigation state management."""

from __future__ import annotations

import pytest

from ubo_app.store.core.types import (
    ApplicationStackItem,
    MenuStackItem,
    NavigateClearAction,
    NavigatePopAction,
    NavigatePushMenuAction,
    PopApplicationAction,
    PushApplicationAction,
    SetPageIndexAction,
    StackItemType,
)


class TestNavigationStackTypes:
    """Test navigation stack type definitions."""

    def test_menu_stack_item_defaults(self) -> None:
        """Test MenuStackItem has correct defaults."""
        item = MenuStackItem(key='test')
        assert item.type == StackItemType.MENU
        assert item.key == 'test'
        assert item.title == ''
        assert item.menu_path == ()
        assert item.page_index == 0

    def test_menu_stack_item_with_values(self) -> None:
        """Test MenuStackItem with custom values."""
        item = MenuStackItem(
            key='settings',
            title='Settings',
            menu_path=('main', 'settings'),
            page_index=2,
        )
        assert item.key == 'settings'
        assert item.title == 'Settings'
        assert item.menu_path == ('main', 'settings')
        assert item.page_index == 2

    def test_application_stack_item_defaults(self) -> None:
        """Test ApplicationStackItem has correct defaults."""
        item = ApplicationStackItem(
            application_id='my_app',
            instance_id='inst-123',
        )
        assert item.type == StackItemType.APPLICATION
        assert item.application_id == 'my_app'
        assert item.instance_id == 'inst-123'
        assert item.title == ''
        assert item.initialization_args == ()
        assert item.initialization_kwargs == {}

    def test_application_stack_item_generates_instance_id(self) -> None:
        """Test ApplicationStackItem generates unique instance_id if not provided."""
        item1 = ApplicationStackItem(application_id='app')
        item2 = ApplicationStackItem(application_id='app')
        # Both should have instance_ids
        assert item1.instance_id
        assert item2.instance_id
        # They should be different (uuid4)
        assert item1.instance_id != item2.instance_id


class TestNavigationActions:
    """Test navigation action definitions."""

    def test_navigate_push_menu_action(self) -> None:
        """Test NavigatePushMenuAction creation."""
        action = NavigatePushMenuAction(item_key='main', title='Main Menu')
        assert action.item_key == 'main'
        assert action.title == 'Main Menu'

    def test_navigate_pop_action(self) -> None:
        """Test NavigatePopAction creation."""
        action = NavigatePopAction()
        assert action is not None

    def test_navigate_clear_action(self) -> None:
        """Test NavigateClearAction creation."""
        action = NavigateClearAction()
        assert action is not None

    def test_set_page_index_action(self) -> None:
        """Test SetPageIndexAction creation."""
        action = SetPageIndexAction(page_index=3)
        assert action.page_index == 3

    def test_push_application_action(self) -> None:
        """Test PushApplicationAction creation."""
        action = PushApplicationAction(
            application_id='test_app',
            title='Test Application',
        )
        assert action.application_id == 'test_app'
        assert action.title == 'Test Application'
        # instance_id should be auto-generated
        assert action.instance_id

    def test_pop_application_action(self) -> None:
        """Test PopApplicationAction creation."""
        action = PopApplicationAction(instance_id='inst-456')
        assert action.instance_id == 'inst-456'


@pytest.mark.asyncio
async def test_navigation_types_import() -> None:
    """Test that all navigation types can be imported."""
    from ubo_app.store.core.selectors import (
        select_breadcrumb,
        select_can_go_down,
        select_can_go_up,
        select_current_menu,
        select_current_page_index,
        select_is_at_home,
        select_navigation_stack,
        select_stack_depth,
        select_top_stack_item,
        select_total_pages,
    )
    from ubo_app.store.core.ui_types import (
        RenderedApplication,
        RenderedItem,
        RenderedItemType,
        RenderedPage,
        RenderedView,
    )

    # Verify imports succeeded
    assert RenderedItemType.ACTION == 'action'
    assert RenderedItem is not None
    assert RenderedPage is not None
    assert RenderedApplication is not None
    assert RenderedView is not None
    assert select_navigation_stack is not None
    assert select_stack_depth is not None
    assert select_is_at_home is not None
    assert select_top_stack_item is not None
    assert select_current_menu is not None
    assert select_current_page_index is not None
    assert select_total_pages is not None
    assert select_breadcrumb is not None
    assert select_can_go_up is not None
    assert select_can_go_down is not None
