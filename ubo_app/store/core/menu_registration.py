"""Menu registration logic extracted from the reducer.

This module provides functions for registering apps and settings in the
registered_apps dict. Dynamic menus are updated via autoruns in menus.py.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ubo_app.store.core.stack_ops import pop_stack
from ubo_app.store.core.types.state import RegisteredAppEntry

if TYPE_CHECKING:
    from ubo_app.store.core.types import (
        DeregisterRegularAppAction,
        MainState,
        RegisterRegularAppAction,
        RegisterSettingAppAction,
        StackChangedEvent,
    )
    from ubo_app.store.settings.types import SettingsServiceSetStatusAction


def register_setting_app(
    state: MainState,
    action: RegisterSettingAppAction,
) -> MainState:
    """Register a setting app in the appropriate settings category.

    Args:
        state: Current main state.
        action: The registration action with label, icon, action_id, and category.

    Returns:
        New state with the setting app registered.

    Raises:
        ValueError: If an app with the same key already exists.

    """
    if not action.service:
        return state

    key = f'{action.service}:'
    if action.key is not None:
        key += action.key

    if key in state.registered_apps:
        msg = f"""Settings application with key "{key}", in category \
"{action.category}", already exists. Consider providing a unique `key` field \
for the `RegisterSettingAppAction` instance."""
        raise ValueError(msg)

    priorities = {
        **state.settings_items_priorities,
        key: action.priority,
    }

    # Store in registered_apps dict
    entry = RegisteredAppEntry(
        key=key,
        label=action.label,
        icon=action.icon,
        action_id=action.action_id,
        background_color=action.background_color,
        priority=action.priority,
        category=action.category.value,
    )

    return replace(
        state,
        settings_items_priorities=priorities,
        registered_apps={**state.registered_apps, key: entry},
    )


def register_regular_app(
    state: MainState,
    action: RegisterRegularAppAction,
) -> MainState:
    """Register a regular app in the Apps menu.

    Args:
        state: Current main state.
        action: The registration action with label, icon, action_id.

    Returns:
        New state with the app registered.

    Raises:
        ValueError: If an app with the same key already exists.

    """
    if not action.service:
        return state

    key = f'{action.service}:'
    if action.key is not None:
        key += action.key

    if key in state.registered_apps:
        msg = f"""Regular application with key "{key}", already exists. \
Consider providing a unique `key` field for the `RegisterRegularAppAction` instance."""
        raise ValueError(msg)

    priorities = {
        **state.apps_items_priorities,
        key: action.priority,
    }

    # Store in registered_apps dict
    entry = RegisteredAppEntry(
        key=key,
        label=action.label,
        icon=action.icon,
        action_id=action.action_id,
        background_color=action.background_color,
        priority=action.priority,
        category=None,
        app_category=action.app_category,
    )

    return replace(
        state,
        apps_items_priorities=priorities,
        registered_apps={**state.registered_apps, key: entry},
    )


def deregister_regular_app(
    state: MainState,
    action: DeregisterRegularAppAction,
) -> tuple[MainState, list[StackChangedEvent]]:
    """Deregister a regular app from the Apps menu.

    Args:
        state: Current main state.
        action: The deregistration action.

    Returns:
        Tuple of (new state, list of StackChangedEvent to emit).

    """
    from ubo_app.store.core.types import StackChangedEvent

    if action.service is None:
        return state, []

    key = f'{action.service}:'
    if action.key is not None:
        key += action.key

    original_stack = state.stack

    # Pop stack if we're inside the app's menu
    path = state.path
    if path[:2] == ('main', 'apps') and key in path[2:]:
        n_pops = len(path) - path.index(key)
        for _ in range(n_pops):
            result = pop_stack(state)
            if result is not None:
                state = result

    # Remove from registered_apps
    new_registered_apps = {
        k: v for k, v in state.registered_apps.items() if k != key
    }

    new_state = replace(
        state,
        registered_apps=new_registered_apps,
    )

    events: list[StackChangedEvent] = []
    if new_state.stack != original_stack:
        events = [StackChangedEvent(stack=new_state.stack)]

    return new_state, events


def update_service_status(
    state: MainState,
    action: SettingsServiceSetStatusAction,
) -> tuple[MainState, list[StackChangedEvent]]:
    """Update menu state when a service's status changes to inactive.

    Removes apps and settings registered by the deactivated service.

    Args:
        state: Current main state.
        action: The service status change action.

    Returns:
        Tuple of (new state, list of StackChangedEvent to emit).

    """
    from ubo_app.store.core.types import StackChangedEvent

    original_stack = state.stack

    # Use reactive path from state (computed by reducer)
    path = state.path
    n_pops = 0
    # Exit open menus of the deregistered app
    if (
        path[:2] == ('main', 'apps')
        and len(path) > 2  # noqa: PLR2004
        and any(
            element.startswith(f'{action.service_id}:')
            for element in path[2:]
        )
    ):
        n_pops = len(path) - next(
            index
            for index, element in enumerate(path)
            if index >= 2  # noqa: PLR2004
            and element.startswith(f'{action.service_id}:')
        )
    if (
        path[:2] == ('main', 'settings')
        and len(path) > 3  # noqa: PLR2004
        and path[3].startswith(f'{action.service_id}:')
    ):
        n_pops = len(path) - 3

    for _ in range(n_pops):
        result = pop_stack(state)
        if result is not None:
            state = result

    # Remove from registered_apps
    new_registered_apps = {
        k: v
        for k, v in state.registered_apps.items()
        if not k.startswith(f'{action.service_id}:')
    }

    new_state = replace(
        state,
        registered_apps=new_registered_apps,
    )

    events: list[StackChangedEvent] = []
    if new_state.stack != original_stack:
        events = [StackChangedEvent(stack=new_state.stack)]

    return new_state, events
