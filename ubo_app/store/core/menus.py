"""Dynamic menu definitions and setup for the Ubo GUI."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from redux import AutorunOptions

from ubo_app.logger import logger
from ubo_app.store.core.constants import (
    MENU_NAVIGATE_PREFIX,
    MENU_SELECT_PREFIX,
    NOTIFICATION_DISPLAY_PREFIX,
    SETTINGS_CATEGORY_ICONS,
)
from ubo_app.store.core.types import (
    MenuItemData,
    PowerOffAction,
    RebootAction,
    SettingsCategory,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import register_category_icon
from ubo_app.store.main import store

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_app.store.services.notifications import Notification

# =============================================================================
# Dynamic Menu IDs for Core Menus
# =============================================================================
NOTIFICATIONS_MENU_ID = 'notifications:list'
HOME_MENU_ID = 'home:main'
MAIN_MENU_ID = 'main:menu'
APPS_MENU_ID = 'apps:list'
SETTINGS_MENU_ID = 'settings:categories'
POWER_MENU_ID = 'power:options'


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
        now = time.time()
        items = tuple(
            MenuItemData(
                key=str(notification.id),
                label=notification.title,
                icon=notification.icon,
                color='black',
                background_color=notification.color,
                action_id=f'{NOTIFICATION_DISPLAY_PREFIX}{notification.id}',
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


# =============================================================================
# Dynamic Menu Initialization Functions
# =============================================================================


def update_main_dynamic_menu() -> None:
    """Update the dynamic menu for Main menu."""
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=MAIN_MENU_ID,
            title='\U000f035cMain',
            items=(
                MenuItemData(
                    key='apps',
                    label='Apps',
                    icon='\U000f003b',
                    action_id=f'{MENU_NAVIGATE_PREFIX}apps',
                ),
                MenuItemData(
                    key='settings',
                    label='Settings',
                    icon='\ue690',
                    action_id=f'{MENU_NAVIGATE_PREFIX}settings',
                ),
                MenuItemData(
                    key='about',
                    label='About',
                    icon='\uf129',
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
            title='\U000f0425Power',
            items=(
                MenuItemData(
                    key='reboot',
                    label='Reboot',
                    icon='\U000f0709',
                    action_id='power:reboot',
                ),
                MenuItemData(
                    key='poweroff',
                    label='Power off',
                    icon='\U000f0425',
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
            icon=SETTINGS_CATEGORY_ICONS.get(category, ''),
            action_id=f'{MENU_NAVIGATE_PREFIX}settings:{category.value}',
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
    from ubo_app.store.core.view_registry import get_apps_menu_title

    # Apps menu items are added dynamically by services via RegisterRegularAppAction
    # This just sets up the initial empty state
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=APPS_MENU_ID,
            title=get_apps_menu_title(),
            items=(),
            placeholder='No apps',
        ),
    )


def update_settings_category_dynamic_menus() -> None:
    """Initialize empty dynamic menus for each settings category."""
    for category in SettingsCategory:
        icon = SETTINGS_CATEGORY_ICONS.get(category, '')
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=f'settings:{category.value}',
                title=f'{icon}{category.value}',
                items=(),
                placeholder='No settings in this category',
            ),
        )


def update_home_dynamic_menu() -> None:
    """Update the dynamic menu for the home screen."""
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=HOME_MENU_ID,
            title='Home',
            items=(
                MenuItemData(
                    key='main',
                    label='',
                    icon='\U000f035c',
                    is_short=True,
                    action_id=f'{MENU_NAVIGATE_PREFIX}main',
                ),
                MenuItemData(
                    key='notifications',
                    label='',
                    icon='\ueaa2',
                    is_short=True,
                    action_id=f'{MENU_NAVIGATE_PREFIX}notifications',
                ),
                MenuItemData(
                    key='power',
                    label='',
                    icon='\U000f0425',
                    is_short=True,
                    action_id=f'{MENU_NAVIGATE_PREFIX}power',
                ),
            ),
            placeholder='',
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

    register_action(f'{MENU_NAVIGATE_PREFIX}apps', _navigate_to_apps)
    register_action(f'{MENU_NAVIGATE_PREFIX}settings', _navigate_to_settings)
    register_action(f'{MENU_NAVIGATE_PREFIX}main', _navigate_to_main)
    register_action(f'{MENU_NAVIGATE_PREFIX}notifications', _navigate_to_notifications)
    register_action(f'{MENU_NAVIGATE_PREFIX}power', _navigate_to_power)


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
            f'{MENU_NAVIGATE_PREFIX}settings:{category.value}',
            _make_category_handler(category),
        )


def _register_about_action_handler() -> None:
    """Register action handler for about menu."""
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.core.types import StackPushMenuAction
    from ubo_app.store.update_manager.utils import (
        open_about_menu as _open_about,
    )
    from ubo_app.store.update_manager.utils import (
        register_about_path_matcher,
    )

    register_about_path_matcher()

    def _handle_about() -> None:
        _open_about()
        store.dispatch(StackPushMenuAction(menu_key='about:main'))

    register_action('menu:about', _handle_about)


def _register_core_action_handlers() -> None:
    """Register all action handlers for core menu items."""
    _register_power_action_handlers()
    _register_navigation_action_handlers()
    _register_settings_category_handlers()
    _register_about_action_handler()


def _register_core_path_matchers() -> None:
    """Register path matchers for core menu navigation.

    This maps navigation paths to dynamic menu IDs for the core UI.
    """
    from ubo_app.store.core.view_registry import register_path_menu_matcher

    # Core menu path mappings
    core_path_mappings: dict[tuple[str, ...], str] = {
        ('main',): MAIN_MENU_ID,
        ('main', 'apps'): APPS_MENU_ID,
        ('main', 'settings'): SETTINGS_MENU_ID,
        ('notifications',): NOTIFICATIONS_MENU_ID,
        ('power',): POWER_MENU_ID,
    }

    # Add settings category path mappings
    for category in SettingsCategory:
        core_path_mappings[('main', 'settings', category.value)] = (
            f'settings:{category.value}'
        )

    def _core_path_matcher(path: tuple[str, ...]) -> str | None:
        return core_path_mappings.get(path)

    # Register with high priority so core paths are matched first
    register_path_menu_matcher('core:menus', _core_path_matcher, priority=100)


def _register_category_icons() -> None:
    """Register icons for settings categories."""
    for category, icon in SETTINGS_CATEGORY_ICONS.items():
        register_category_icon(category, icon)


def setup_core_dynamic_menus() -> None:
    """Set up dynamic menus and action handlers for core UI.

    This should be called once after the store is initialized.
    """
    # Register category icons
    _register_category_icons()

    # Register core path matchers
    _register_core_path_matchers()

    # Register action handlers
    _register_core_action_handlers()

    # Initialize dynamic menus
    update_home_dynamic_menu()
    update_main_dynamic_menu()
    update_power_dynamic_menu()
    update_settings_categories_dynamic_menu()
    update_apps_dynamic_menu()
    update_settings_category_dynamic_menus()

    # Set up dynamic menus for System settings (General, Services, Third Party)
    from ubo_app.store.settings.dynamic_system_menus import (
        setup_dynamic_system_menus,
    )

    setup_dynamic_system_menus()

    # Set up autoruns to keep dynamic menus in sync with registered_apps
    _setup_registered_apps_autoruns()


def _setup_registered_apps_autoruns() -> None:
    """Set up autoruns that keep dynamic menus in sync with registered_apps.

    Watches `state.main.registered_apps` and auto-populates the apps menu
    and each settings category menu from the registered entries.

    Optimisation: the settings autorun caches computed items per category
    and only dispatches ``UpdateDynamicMenuAction`` for categories whose
    items actually changed, avoiding 6 redundant dispatches when a single
    service registers.
    """
    from ubo_app.store.core.types.state import RegisteredAppEntry
    from ubo_app.store.core.view_registry import get_apps_menu_title

    @store.autorun(
        lambda state: (
            state.main.registered_apps,
            state.main.apps_items_priorities,
        ),
        options=AutorunOptions(default_value=None),
    )
    def _sync_apps_dynamic_menu(
        data: tuple[dict[str, RegisteredAppEntry], dict[str, int]] | None,
    ) -> None:
        """Sync apps dynamic menu from registered_apps."""
        if data is None:
            return

        registered_apps, priorities = data

        # Filter to regular apps (no category)
        app_entries = [
            (key, entry)
            for key, entry in registered_apps.items()
            if isinstance(entry, RegisteredAppEntry) and entry.category is None
        ]

        # Sort by priority (descending) then key
        def sort_key(pair: tuple[str, RegisteredAppEntry]) -> tuple[int, str]:
            return (-(priorities.get(pair[0], 0) or 0), pair[0])

        app_entries.sort(key=sort_key)

        items = tuple(
            MenuItemData(
                key=key,
                label=entry.label,
                icon=entry.icon,
                action_id=entry.action_id or f'{MENU_SELECT_PREFIX}{key}',
                background_color=entry.background_color,
            )
            for key, entry in app_entries
        )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=APPS_MENU_ID,
                title=get_apps_menu_title(),
                items=items,
                placeholder='No apps',
            ),
        )

    # Cache of last-dispatched items per settings category so we only
    # dispatch UpdateDynamicMenuAction for categories that actually changed.
    _last_category_items: dict[SettingsCategory, tuple[MenuItemData | None, ...]] = {}

    @store.autorun(
        lambda state: (
            state.main.registered_apps,
            state.main.settings_items_priorities,
        ),
        options=AutorunOptions(default_value=None),
    )
    def _sync_settings_dynamic_menus(
        data: tuple[dict[str, RegisteredAppEntry], dict[str, int]] | None,
    ) -> None:
        """Sync settings category dynamic menus from registered_apps."""
        if data is None:
            return

        registered_apps, priorities = data

        for category in SettingsCategory:
            # Filter to settings in this category
            category_entries = [
                (key, entry)
                for key, entry in registered_apps.items()
                if isinstance(entry, RegisteredAppEntry)
                and entry.category == category.value
            ]

            # Sort by priority (descending) then key
            def sort_key(
                pair: tuple[str, RegisteredAppEntry],
                *,
                _priorities: dict[str, int] = priorities,
            ) -> tuple[int, str]:
                return (-(_priorities.get(pair[0], 0) or 0), pair[0])

            category_entries.sort(key=sort_key)

            icon = SETTINGS_CATEGORY_ICONS.get(category, '')
            service_items = tuple(
                MenuItemData(
                    key=key,
                    label=entry.label,
                    icon=entry.icon,
                    action_id=entry.action_id or f'{MENU_SELECT_PREFIX}{key}',
                    background_color=entry.background_color,
                )
                for key, entry in category_entries
            )

            # For System category, prepend static sub-menu items
            # (General, Services, Third Party) so they aren't lost
            # when the autorun overwrites the menu.
            if category == SettingsCategory.SYSTEM:
                from ubo_app.store.settings.dynamic_system_menus import (
                    get_system_submenu_items,
                )

                items: tuple[MenuItemData | None, ...] = (
                    *get_system_submenu_items(),
                    *service_items,
                )
            else:
                items = service_items

            # Only dispatch if this category's items actually changed
            if _last_category_items.get(category) == items:
                continue
            _last_category_items[category] = items

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'settings:{category.value}',
                    title=f'{icon}{category.value}',
                    items=items,
                    placeholder='No settings in this category',
                ),
            )
