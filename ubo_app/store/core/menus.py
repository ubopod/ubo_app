"""Menu definitions for the Ubo GUI."""

from __future__ import annotations

import math
import socket
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadlessMenu, SubMenuItem

from ubo_app.logger import logger
from ubo_app.store.core.types import (
    SETTINGS_ICONS,
    MenuItemData,
    PowerOffAction,
    RebootAction,
    SettingsCategory,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Notification,
    NotificationsDisplayAction,
)
from ubo_app.store.settings.menu import SYSTEM_MENU
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.store.update_manager.utils import open_about_menu

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_gui.menu.types import Item

# =============================================================================
# Dynamic Menu IDs for Core Menus
# =============================================================================
NOTIFICATIONS_MENU_ID = 'notifications:list'
HOME_MENU_ID = 'home:main'
MAIN_MENU_ID = 'main:menu'
APPS_MENU_ID = 'apps:list'
SETTINGS_MENU_ID = 'settings:categories'
POWER_MENU_ID = 'power:options'


APPS_MENU = HeadlessMenu(
    title='󰀻Docker Apps',
    items=[],
    placeholder='No apps',
)

SETTINGS_MENU = HeadlessMenu(
    title='Settings',
    items=[
        SubMenuItem(
            key=category,
            label=category,
            icon=SETTINGS_ICONS[category],
            sub_menu=HeadlessMenu(
                title=SETTINGS_ICONS[category] + category,
                items=SYSTEM_MENU if category is SettingsCategory.SYSTEM else [],
                placeholder='No settings in this category',
            ),
        )
        for category in SettingsCategory
    ],
)

MAIN_MENU = HeadlessMenu(
    title='󰍜Main',
    items=[
        SubMenuItem(
            key='apps',
            label='Apps',
            icon='󰀻',
            sub_menu=APPS_MENU,
        ),
        SubMenuItem(
            key='settings',
            label='Settings',
            icon='',
            sub_menu=SETTINGS_MENU,
        ),
        ActionItem(
            key='about',
            label='About',
            icon='',
            action=open_about_menu,
        ),
    ],
)


@store.autorun(
    lambda state: state.notifications.unread_count,
    options=AutorunOptions(default_value='Notifications (not loaded)'),
)
def _notifications_title(unread_count: int) -> str:
    return f'Notifications ({unread_count})'


@store.autorun(
    lambda state: state.notifications.notifications,
    options=AutorunOptions(default_value=None),
)
def update_notifications_dynamic_menu(
    notifications: Sequence[Notification] | None,
) -> None:
    """Update the dynamic menu for notifications (dumb UI architecture)."""
    if notifications is None:
        items: tuple[MenuItemData | None, ...] = ()
    else:
        now = datetime.now(tz=UTC)
        items = tuple(
            MenuItemData(
                key=str(notification.id),
                label=notification.title,
                icon=notification.icon,
                color='black',
                background_color=notification.color,
                action_id=f'notification:display:{notification.id}',
            )
            for notification in notifications
            if notification.expiration_timestamp is None
            or notification.expiration_timestamp > now
        )

    logger.debug(
        '[Notifications] Updating dynamic menu: %d notifications',
        len(items),
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=NOTIFICATIONS_MENU_ID,
            title='Notifications',
            items=items,
            placeholder='No notifications',
        ),
    )


@store.autorun(
    lambda state: state.notifications.notifications,
    options=AutorunOptions(default_value=[]),
)
def notifications_menu_items(notifications: Sequence[Notification]) -> list[Item]:
    """Return a list of menu items for the notification manager."""
    return [
        UboDispatchItem(
            key=str(notification.id),
            label=notification.title,
            icon=notification.icon,
            color='black',
            background_color=notification.color,
            store_action=NotificationsDisplayAction(
                notification=notification,
                index=index,
                count=len(notifications),
            ),
            progress=None
            if notification.progress is None or math.isnan(notification.progress)
            else notification.progress,
        )
        for index, notification in enumerate(notifications)
        if notification.expiration_timestamp is None
        or notification.expiration_timestamp > datetime.now(tz=UTC)
    ]


@store.autorun(
    lambda state: len(state.notifications.notifications),
    options=AutorunOptions(default_value='white'),
)
def _notifications_color(unread_count: int) -> str:
    return 'yellow' if unread_count > 0 else 'white'


HOME_MENU = HeadlessMenu(
    title=f'󰋜{socket.gethostname()}.local',
    items=[
        SubMenuItem(
            key='main',
            label='',
            sub_menu=MAIN_MENU,
            icon='󰍜',
            is_short=True,
        ),
        SubMenuItem(
            key='notifications',
            label='',
            sub_menu=HeadlessMenu(
                title=_notifications_title,
                items=notifications_menu_items,
                placeholder='No notifications',
            ),
            color=_notifications_color,
            icon='',
            is_short=True,
        ),
        SubMenuItem(
            key='power',
            label='',
            sub_menu=HeadlessMenu(
                title='󰐥Power',
                items=[
                    UboDispatchItem(
                        label='Reboot',
                        store_action=RebootAction(),
                        icon='󰜉',
                    ),
                    UboDispatchItem(
                        label='Power off',
                        store_action=PowerOffAction(),
                        icon='󰐥',
                    ),
                ],
            ),
            icon='󰐥',
            is_short=True,
        ),
    ],
)


# =============================================================================
# Dynamic Menu Autoruns for Dumb UI Architecture
# =============================================================================


def update_main_dynamic_menu() -> None:
    """Update the dynamic menu for Main menu."""
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=MAIN_MENU_ID,
            title='󰍜Main',
            items=(
                MenuItemData(
                    key='apps',
                    label='Apps',
                    icon='󰀻',
                    action_id='menu:navigate:apps',
                ),
                MenuItemData(
                    key='settings',
                    label='Settings',
                    icon='',
                    action_id='menu:navigate:settings',
                ),
                MenuItemData(
                    key='about',
                    label='About',
                    icon='',
                    action_id='menu:about',
                ),
            ),
            placeholder='',
        ),
    )


def update_power_dynamic_menu() -> None:
    """Update the dynamic menu for Power options."""
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=POWER_MENU_ID,
            title='󰐥Power',
            items=(
                MenuItemData(
                    key='reboot',
                    label='Reboot',
                    icon='󰜉',
                    action_id='power:reboot',
                ),
                MenuItemData(
                    key='poweroff',
                    label='Power off',
                    icon='󰐥',
                    action_id='power:off',
                ),
            ),
            placeholder='',
        ),
    )


def update_settings_categories_dynamic_menu() -> None:
    """Update the dynamic menu for Settings categories."""
    items = tuple(
        MenuItemData(
            key=category.value,
            label=category.value,
            icon=SETTINGS_ICONS[category],
            action_id=f'menu:navigate:settings:{category.value}',
        )
        for category in SettingsCategory
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=SETTINGS_MENU_ID,
            title='Settings',
            items=items,
            placeholder='No settings categories',
        ),
    )


def update_apps_dynamic_menu() -> None:
    """Update the dynamic menu for Apps (placeholder - filled by services)."""
    # Apps menu items are added dynamically by services via RegisterRegularAppAction
    # This just sets up the initial empty state
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=APPS_MENU_ID,
            title='󰀻Docker Apps',
            items=(),
            placeholder='No apps',
        ),
    )


# =============================================================================
# Action Handler Registration for Core Menus
# =============================================================================


def _register_power_action_handlers() -> None:
    """Register action handlers for power menu items."""
    from ubo_app.store.core.action_registry import register_action

    def _handle_reboot() -> None:
        store.dispatch(RebootAction())

    def _handle_poweroff() -> None:
        store.dispatch(PowerOffAction())

    register_action('power:reboot', _handle_reboot)
    register_action('power:off', _handle_poweroff)


def _register_navigation_action_handlers() -> None:
    """Register action handlers for menu navigation."""
    from ubo_app.store.core.action_registry import register_action

    def _navigate_to_apps() -> None:
        store.dispatch(StackPushMenuAction(menu_key='apps'))

    def _navigate_to_settings() -> None:
        store.dispatch(StackPushMenuAction(menu_key='settings'))

    def _navigate_to_main() -> None:
        store.dispatch(StackPushMenuAction(menu_key='main'))

    def _navigate_to_notifications() -> None:
        store.dispatch(StackPushMenuAction(menu_key='notifications'))

    def _navigate_to_power() -> None:
        store.dispatch(StackPushMenuAction(menu_key='power'))

    register_action('menu:navigate:apps', _navigate_to_apps)
    register_action('menu:navigate:settings', _navigate_to_settings)
    register_action('menu:navigate:main', _navigate_to_main)
    register_action('menu:navigate:notifications', _navigate_to_notifications)
    register_action('menu:navigate:power', _navigate_to_power)


def _make_category_handler(cat: SettingsCategory) -> Callable[[], None]:
    """Create a handler function for settings category navigation."""
    def _handler() -> None:
        store.dispatch(StackPushMenuAction(menu_key=cat.value))

    return _handler


def _register_settings_category_handlers() -> None:
    """Register action handlers for settings category navigation."""
    from ubo_app.store.core.action_registry import register_action

    for category in SettingsCategory:
        register_action(
            f'menu:navigate:settings:{category.value}',
            _make_category_handler(category),
        )


def _register_about_action_handler() -> None:
    """Register action handler for about menu."""
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.update_manager.utils import open_about_menu as _open_about

    def _handle_about() -> None:
        _open_about()

    register_action('menu:about', _handle_about)


def _register_core_action_handlers() -> None:
    """Register all action handlers for core menu items."""
    _register_power_action_handlers()
    _register_navigation_action_handlers()
    _register_settings_category_handlers()
    _register_about_action_handler()


def setup_core_dynamic_menus() -> None:
    """Set up dynamic menus and action handlers for core UI.

    This should be called once after the store is initialized.
    """
    # Register action handlers
    _register_core_action_handlers()

    # Initialize dynamic menus
    update_main_dynamic_menu()
    update_power_dynamic_menu()
    update_settings_categories_dynamic_menu()
    update_apps_dynamic_menu()
