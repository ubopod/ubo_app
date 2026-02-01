"""Menu registration logic extracted from the reducer.

This module provides functions for registering apps and settings in the menu tree.
These functions reduce the complexity of the main reducer.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from ubo_gui.menu.types import Menu, SubMenuItem, menu_items

from ubo_app.store.core.menu_adapter import find_sub_menu_item

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item

    from ubo_app.store.core.types import (
        DeregisterRegularAppAction,
        MainState,
        RegisterRegularAppAction,
        RegisterSettingAppAction,
    )
    from ubo_app.store.settings.types import SettingsServiceSetStatusAction


def register_setting_app(
    state: MainState,
    action: RegisterSettingAppAction,
) -> MainState:
    """Register a setting app in the appropriate settings category.

    Args:
        state: Current main state.
        action: The registration action with menu item and category.

    Returns:
        New state with the setting app registered.

    Raises:
        ValueError: If an app with the same key already exists.

    """
    menu = state.menu
    if not menu or not action.service:
        return state

    root_menu_items = menu_items(menu)
    main_menu_item = find_sub_menu_item(root_menu_items, 'main')
    main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
    settings_menu_item = find_sub_menu_item(main_menu_items, 'settings')
    settings_menu_items = menu_items(cast('Menu', settings_menu_item.sub_menu))

    category_menu_item = cast(
        'SubMenuItem',
        next(
            item
            for item in settings_menu_items
            if item.label == action.category
        ),
    )

    key = f'{action.service}:'
    if action.key is not None:
        key += action.key

    priorities = {
        **state.settings_items_priorities,
        key: action.priority,
    }

    def sort_key(item: Item) -> tuple[int, str]:
        key_ = item.key or (item.label() if callable(item.label) else item.label)
        return (-(priorities.get(key_, 0) or 0), key_)

    if any(
        item.key == key
        for item in cast(
            'Sequence[Item]',
            cast('Menu', category_menu_item.sub_menu).items,
        )
    ):
        msg = f"""Settings application with key "{key}", in category \
"{category_menu_item.label}", already exists. Consider providing a unique `key` field \
for the `RegisterSettingAppAction` instance."""
        raise ValueError(msg)

    menu_item = replace(action.menu_item, key=key)
    new_items = sorted(
        [
            *cast(
                'Sequence[Item]',
                cast('Menu', category_menu_item.sub_menu).items,
            ),
            menu_item,
        ],
        key=sort_key,
    )

    new_category_menu_item = replace(
        category_menu_item,
        sub_menu=replace(
            cast('Menu', category_menu_item.sub_menu),
            items=new_items,
        ),
    )

    new_settings_menu_item = replace(
        settings_menu_item,
        sub_menu=replace(
            cast('Menu', settings_menu_item.sub_menu),
            items=[
                new_category_menu_item if item == category_menu_item else item
                for item in settings_menu_items
            ],
        ),
    )

    new_main_menu_item = replace(
        main_menu_item,
        sub_menu=replace(
            cast('Menu', main_menu_item.sub_menu),
            items=[
                new_settings_menu_item if item == settings_menu_item else item
                for item in main_menu_items
            ],
        ),
    )

    return replace(
        state,
        settings_items_priorities=priorities,
        menu=replace(
            menu,
            items=[
                new_main_menu_item if item == main_menu_item else item
                for item in root_menu_items
            ],
        ),
    )


def register_regular_app(
    state: MainState,
    action: RegisterRegularAppAction,
) -> MainState:
    """Register a regular app in the Apps menu.

    Args:
        state: Current main state.
        action: The registration action with menu item.

    Returns:
        New state with the app registered.

    Raises:
        ValueError: If an app with the same key already exists.

    """
    menu = state.menu
    if not menu or not action.service:
        return state

    root_menu_items = menu_items(menu)
    main_menu_item = find_sub_menu_item(root_menu_items, 'main')
    main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
    apps_menu_item = find_sub_menu_item(main_menu_items, 'apps')
    apps_menu_items = menu_items(cast('Menu', apps_menu_item.sub_menu))

    key = f'{action.service}:'
    if action.key is not None:
        key += action.key

    if any(item.key == key for item in apps_menu_items):
        msg = f"""Regular application with key "{key}", already exists. \
Consider providing a unique `key` field for the `RegisterRegularAppAction` instance."""
        raise ValueError(msg)

    priorities = {
        **state.apps_items_priorities,
        key: action.priority,
    }

    def sort_key(item: Item) -> tuple[int, str]:
        key_ = item.key or (item.label() if callable(item.label) else item.label)
        return (-(priorities.get(key_, 0) or 0), key_)

    menu_item = replace(action.menu_item, key=key)
    new_items = sorted(
        [
            *cast('Sequence[Item]', apps_menu_items),
            menu_item,
        ],
        key=sort_key,
    )

    apps_menu_item = replace(
        apps_menu_item,
        sub_menu=replace(
            cast('Menu', apps_menu_item.sub_menu),
            items=new_items,
        ),
    )

    main_menu_item = replace(
        main_menu_item,
        sub_menu=replace(
            cast('Menu', main_menu_item.sub_menu),
            items=[
                apps_menu_item if item.key == 'apps' else item
                for item in main_menu_items
            ],
        ),
    )

    return replace(
        state,
        menu=replace(
            menu,
            items=[
                main_menu_item if index == 0 else item
                for index, item in enumerate(root_menu_items)
            ],
        ),
    )


def deregister_regular_app(
    state: MainState,
    action: DeregisterRegularAppAction,
) -> tuple[MainState, list]:
    """Deregister a regular app from the Apps menu.

    Args:
        state: Current main state.
        action: The deregistration action.

    Returns:
        Tuple of (new state, list of MenuGoBackEvent to emit).

    """
    from ubo_app.store.core.types import MenuGoBackEvent

    if action.service is None:
        return state, []

    key = f'{action.service}:'
    if action.key is not None:
        key += action.key

    menu = state.menu
    if not menu:
        return state, []

    root_menu_items = menu_items(menu)
    main_menu_item = find_sub_menu_item(root_menu_items, 'main')
    main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
    apps_menu_item = find_sub_menu_item(main_menu_items, 'apps')
    apps_menu_items = menu_items(cast('Menu', apps_menu_item.sub_menu))

    new_items = [item for item in apps_menu_items if item.key != key]

    new_apps_menu_item = replace(
        apps_menu_item,
        sub_menu=replace(
            cast('Menu', apps_menu_item.sub_menu),
            items=new_items,
        ),
    )

    new_main_menu_item = replace(
        main_menu_item,
        sub_menu=replace(
            cast('Menu', main_menu_item.sub_menu),
            items=[
                new_apps_menu_item if item == apps_menu_item else item
                for item in main_menu_items
            ],
        ),
    )

    events: list[MenuGoBackEvent] = []

    if state.path[:3] == ['main', 'apps', key]:
        events = [MenuGoBackEvent()] * (len(state.path) - 2)

    new_state = replace(
        state,
        menu=replace(
            menu,
            items=[
                new_main_menu_item if item == main_menu_item else item
                for item in root_menu_items
            ],
        ),
    )

    return new_state, events


def update_service_status(
    state: MainState,
    action: SettingsServiceSetStatusAction,
) -> tuple[MainState, list]:
    """Update menu state when a service's status changes to inactive.

    Removes apps and settings registered by the deactivated service.

    Args:
        state: Current main state.
        action: The service status change action.

    Returns:
        Tuple of (new state, list of MenuGoBackEvent to emit).

    """
    from ubo_app.store.core.types import MenuGoBackEvent

    menu = state.menu
    if not menu:
        return state, []

    root_menu_items = menu_items(menu)
    main_menu_item = find_sub_menu_item(root_menu_items, 'main')
    main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
    apps_menu_item = find_sub_menu_item(main_menu_items, 'apps')
    apps_menu_items = menu_items(cast('Menu', apps_menu_item.sub_menu))
    settings_menu_item = find_sub_menu_item(main_menu_items, 'settings')
    settings_menu_items = menu_items(cast('Menu', settings_menu_item.sub_menu))

    new_apps_menu_item = replace(
        apps_menu_item,
        sub_menu=replace(
            cast('Menu', apps_menu_item.sub_menu),
            items=[
                item
                for item in apps_menu_items
                if item.key is None
                or not item.key.startswith(f'{action.service_id}:')
            ],
        ),
    )

    new_settings_menu_item = replace(
        settings_menu_item,
        sub_menu=replace(
            cast('Menu', settings_menu_item.sub_menu),
            items=[
                replace(
                    category_menu_item,
                    sub_menu=replace(
                        cast('Menu', category_menu_item.sub_menu),
                        items=[
                            item
                            for item in menu_items(
                                cast('Menu', category_menu_item.sub_menu),
                            )
                            if item.key is None
                            or not item.key.startswith(f'{action.service_id}:')
                        ],
                    ),
                )
                if isinstance(category_menu_item, SubMenuItem)
                else category_menu_item
                for category_menu_item in settings_menu_items
            ],
        ),
    )

    new_main_menu_item = replace(
        main_menu_item,
        sub_menu=replace(
            cast('Menu', main_menu_item.sub_menu),
            items=[
                new_apps_menu_item
                if item == apps_menu_item
                else new_settings_menu_item
                if item == settings_menu_item
                else item
                for item in main_menu_items
            ],
        ),
    )

    events: list[MenuGoBackEvent] = []

    # Exit open menus of the deregistered app
    if (
        state.path[:2] == ['main', 'apps']
        and len(state.path) > 2  # noqa: PLR2004
        and state.path[2].startswith(f'{action.service_id}:')
    ):
        events = [MenuGoBackEvent()] * (len(state.path) - 2)
    if (
        state.path[:2] == ['main', 'settings']
        and len(state.path) > 3  # noqa: PLR2004
        and state.path[3].startswith(f'{action.service_id}:')
    ):
        events = [MenuGoBackEvent()] * (len(state.path) - 3)

    new_state = replace(
        state,
        menu=replace(
            menu,
            items=[
                new_main_menu_item if item == main_menu_item else item
                for item in root_menu_items
            ],
        ),
    )

    return new_state, events
