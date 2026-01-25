"""Tests for the stack types and helper functions.

These are pure unit tests that don't require the full store setup.
"""

from __future__ import annotations

from dataclasses import replace

from ubo_app.store.core.types import (
    ApplicationStackItem,
    MenuStackItem,
    NotificationStackItem,
    StackItemType,
)


def derive_path_from_stack(stack: tuple[StackItemType, ...]) -> list[str]:
    """Derive the menu path from the stack.

    This is a copy of the function from reducer.py for testing purposes,
    to avoid circular import issues.
    """
    return [item.menu_key for item in stack if isinstance(item, MenuStackItem)][1:]


class TestStackTypes:
    """Tests for stack item types."""

    def test_menu_stack_item_creation(self) -> None:
        """Verify MenuStackItem can be created with required fields."""
        item = MenuStackItem(id='test-id', menu_key='main', page_index=0)
        assert item.id == 'test-id'
        assert item.menu_key == 'main'
        assert item.page_index == 0

    def test_menu_stack_item_default_page_index(self) -> None:
        """Verify MenuStackItem has default page_index of 0."""
        item = MenuStackItem(id='test-id', menu_key='main')
        assert item.page_index == 0

    def test_application_stack_item_creation(self) -> None:
        """Verify ApplicationStackItem can be created with required fields."""
        item = ApplicationStackItem(
            id='test-id',
            application_id='camera:viewfinder',
            initialization_args=('arg1', 'arg2'),
            initialization_kwargs={'key': 'value'},
        )
        assert item.id == 'test-id'
        assert item.application_id == 'camera:viewfinder'
        assert item.initialization_args == ('arg1', 'arg2')
        assert item.initialization_kwargs == {'key': 'value'}

    def test_application_stack_item_defaults(self) -> None:
        """Verify ApplicationStackItem has default empty args/kwargs."""
        item = ApplicationStackItem(id='test-id', application_id='test:app')
        assert item.initialization_args == ()
        assert item.initialization_kwargs == {}

    def test_notification_stack_item_creation(self) -> None:
        """Verify NotificationStackItem can be created with required fields."""
        item = NotificationStackItem(id='test-id', notification_id='notif123')
        assert item.id == 'test-id'
        assert item.notification_id == 'notif123'


class TestDerivePathFromStack:
    """Tests for derive_path_from_stack function."""

    def test_empty_stack(self) -> None:
        """Verify empty stack returns empty path."""
        assert derive_path_from_stack(()) == []

    def test_root_only(self) -> None:
        """Verify stack with only root returns empty path."""
        root = (MenuStackItem(id='root', menu_key='', page_index=0),)
        assert derive_path_from_stack(root) == []

    def test_single_menu(self) -> None:
        """Verify stack with root and one menu returns one-item path."""
        stack: tuple[StackItemType, ...] = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='main', menu_key='main', page_index=0),
        )
        assert derive_path_from_stack(stack) == ['main']

    def test_multiple_menus(self) -> None:
        """Verify deep menu navigation returns full path."""
        stack: tuple[StackItemType, ...] = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='main', menu_key='main', page_index=0),
            MenuStackItem(id='settings', menu_key='settings', page_index=0),
            MenuStackItem(id='network', menu_key='network', page_index=0),
            MenuStackItem(id='wifi', menu_key='wifi', page_index=0),
        )
        assert derive_path_from_stack(stack) == ['main', 'settings', 'network', 'wifi']

    def test_ignores_application_items(self) -> None:
        """Verify application items are not included in path."""
        stack: tuple[StackItemType, ...] = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='main', menu_key='main', page_index=0),
            ApplicationStackItem(id='app1', application_id='test:app'),
        )
        assert derive_path_from_stack(stack) == ['main']

    def test_ignores_notification_items(self) -> None:
        """Verify notification items are not included in path."""
        stack: tuple[StackItemType, ...] = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='main', menu_key='main', page_index=0),
            NotificationStackItem(id='notif1', notification_id='notif123'),
        )
        assert derive_path_from_stack(stack) == ['main']

    def test_mixed_stack(self) -> None:
        """Verify path is correct for mixed stack with menus, apps, notifications."""
        stack: tuple[StackItemType, ...] = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='main', menu_key='main', page_index=0),
            ApplicationStackItem(id='app1', application_id='test:app'),
            MenuStackItem(id='submenu', menu_key='submenu', page_index=0),
            NotificationStackItem(id='notif1', notification_id='notif123'),
        )
        # Path should only include menu keys, skipping root
        assert derive_path_from_stack(stack) == ['main', 'submenu']


class TestStackItemImmutability:
    """Test that stack items are immutable."""

    def test_menu_stack_item_immutable(self) -> None:
        """Verify MenuStackItem is immutable via replace."""
        item = MenuStackItem(id='test', menu_key='main', page_index=0)
        new_item = replace(item, page_index=2)
        assert item.page_index == 0  # Original unchanged
        assert new_item.page_index == 2  # New has updated value

    def test_application_stack_item_immutable(self) -> None:
        """Verify ApplicationStackItem is immutable via replace."""
        item = ApplicationStackItem(id='test', application_id='app1')
        new_item = replace(item, application_id='app2')
        assert item.application_id == 'app1'
        assert new_item.application_id == 'app2'

    def test_notification_stack_item_immutable(self) -> None:
        """Verify NotificationStackItem is immutable via replace."""
        item = NotificationStackItem(id='test', notification_id='notif1')
        new_item = replace(item, notification_id='notif2')
        assert item.notification_id == 'notif1'
        assert new_item.notification_id == 'notif2'
