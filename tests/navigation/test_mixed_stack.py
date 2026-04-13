"""Tests for mixed stack navigation.

Menus, apps, and notifications interleaved on the stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    ApplicationViewData,
    CloseApplicationAction,
    HomeViewData,
    MenuViewData,
    NotificationViewData,
    StackPopAction,
    StackPopItemAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner


class TestAppOverMenu:
    """Tests for applications pushed over menus."""

    def test_app_on_top_shows_app_view(self, nav: ReducerRunner) -> None:
        """Verify an application pushed over a menu shows ApplicationViewData."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushApplicationAction(application_id='test:app'))
        assert isinstance(nav.view, ApplicationViewData)

    def test_pop_app_reveals_menu(self, nav: ReducerRunner) -> None:
        """Verify popping an application reveals the underlying menu."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushApplicationAction(application_id='test:app'))
        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, MenuViewData)
        assert nav.state.path == ('main',)

    def test_app_does_not_change_path(self, nav: ReducerRunner) -> None:
        """Verify pushing an application does not alter the menu path."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        path_before = nav.state.path
        nav.dispatch(StackPushApplicationAction(application_id='test:app'))
        assert nav.state.path == path_before


class TestNotificationOverApp:
    """Tests for notifications pushed over applications."""

    def test_notification_on_top_shows_notification(self, nav: ReducerRunner) -> None:
        """Verify a notification pushed over an app shows NotificationViewData."""
        nav.dispatch(StackPushApplicationAction(application_id='test:app'))
        nav.dispatch(StackPushNotificationAction(notification_id='notif-1'))
        assert isinstance(nav.view, NotificationViewData)

    def test_pop_notification_reveals_app(self, nav: ReducerRunner) -> None:
        """Verify popping a notification reveals the underlying application."""
        nav.dispatch(StackPushApplicationAction(application_id='test:app'))
        nav.dispatch(StackPushNotificationAction(notification_id='notif-1'))
        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, ApplicationViewData)


class TestDeepMixedStack:
    """Tests for deeply interleaved stacks."""

    def test_root_menu_app_notification(self, nav: ReducerRunner) -> None:
        """Verify mixed stack shows notification with four items."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushApplicationAction(application_id='app1'))
        nav.dispatch(StackPushNotificationAction(notification_id='n1'))
        assert isinstance(nav.view, NotificationViewData)
        assert len(nav.state.stack) == 4

    def test_pop_through_mixed_stack(self, nav: ReducerRunner) -> None:
        """Verify successive pops traverse notification, app, menu, then home."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushApplicationAction(application_id='app1'))
        nav.dispatch(StackPushNotificationAction(notification_id='n1'))

        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, ApplicationViewData)

        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, MenuViewData)

        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, HomeViewData)

    def test_menu_app_menu_app(self, nav: ReducerRunner) -> None:
        """Menu -> App -> Menu -> App: path skips apps."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushApplicationAction(application_id='app1'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPushApplicationAction(application_id='app2'))
        # Path only includes menu keys
        assert nav.state.path == ('main', 'settings')

    def test_pop_to_root_clears_all_types(self, nav: ReducerRunner) -> None:
        """Verify pop-to-root removes all item types and returns to home."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushApplicationAction(application_id='app1'))
        nav.dispatch(StackPushNotificationAction(notification_id='n1'))
        nav.dispatch(StackPopToRootAction())
        assert len(nav.state.stack) == 1
        assert isinstance(nav.view, HomeViewData)


class TestPopSpecificItem:
    """Tests for popping a specific item from the middle of the stack."""

    def test_pop_middle_item(self, nav: ReducerRunner) -> None:
        """Verify popping a middle item removes it while keeping surrounding items."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushApplicationAction(application_id='app1'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        app_id = nav.state.stack[2].id  # The app item
        nav.dispatch(StackPopItemAction(item_id=app_id))
        assert len(nav.state.stack) == 3
        # Path should still be intact (menu items remain)
        assert nav.state.path == ('main', 'settings')

    def test_pop_top_item(self, nav: ReducerRunner) -> None:
        """Verify popping the top item by ID reveals the item below."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushNotificationAction(notification_id='n1'))
        notif_id = nav.state.stack[-1].id
        nav.dispatch(StackPopItemAction(item_id=notif_id))
        assert isinstance(nav.view, MenuViewData)

    def test_pop_nonexistent_item_is_noop(self, nav: ReducerRunner) -> None:
        """Verify popping a nonexistent item ID does not change the stack."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        original_stack = nav.state.stack
        nav.dispatch(StackPopItemAction(item_id='does-not-exist'))
        assert nav.state.stack == original_stack


class TestCloseAppThenFlashNotification:
    """Verify stack transitions for: close app -> flash notification -> dismiss.

    This models the WiFi delete flow where:
    1. User is on a connection detail page (ApplicationStackItem)
    2. User presses delete -> app is closed, async forget starts
    3. FLASH notification appears (pushed by async completion)
    4. Notification auto-dismisses
    5. User should see the connections list menu (not the stale app)
    """

    def test_close_app_then_notification_returns_to_menu(
        self,
        nav: ReducerRunner,
    ) -> None:
        """Verify full cycle: menu -> app -> close app -> notif -> dismiss -> menu."""
        # Navigate to a menu (simulating wifi connections list)
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        assert isinstance(nav.view, MenuViewData)
        menu_stack_depth = len(nav.state.stack)
        path_before = nav.state.path

        # Push an application
        nav.dispatch(
            StackPushApplicationAction(application_id='test:app'),
        )
        assert isinstance(nav.view, ApplicationViewData)
        app_instance_id = nav.state.stack[-1].id

        # Close the application (simulating the delete button)
        nav.dispatch(
            CloseApplicationAction(application_instance_id=app_instance_id),
        )
        assert isinstance(nav.view, MenuViewData)
        assert len(nav.state.stack) == menu_stack_depth
        assert nav.state.path == path_before

        # FLASH notification arrives (async, from forget_wireless_connection)
        nav.dispatch(StackPushNotificationAction(notification_id='wifi-deleted'))
        assert isinstance(nav.view, NotificationViewData)

        # Notification auto-dismissed (popped from stack)
        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, MenuViewData)
        assert len(nav.state.stack) == menu_stack_depth
        assert nav.state.path == path_before
