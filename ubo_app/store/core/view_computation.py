"""View computation utilities for the dumb UI architecture.

This module provides functions to compute ViewData from the full RootState,
including support for dynamic menus. It can be used by both GUI (Kivy) and
non-GUI contexts (gRPC/TUI).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_gui.menu.types import menu_items

from ubo_app.logger import logger
from ubo_app.store.core.constants import PAGE_SIZE
from ubo_app.store.core.menu_adapter import (
    get_current_menu_from_stack,
    item_to_menu_item_data,
)
from ubo_app.store.core.types import (
    ApplicationStackItem,
    ApplicationViewData,
    HomeViewData,
    MenuStackItem,
    MenuViewData,
    NotificationStackItem,
    NotificationViewData,
)
from ubo_app.store.core.view_helpers import (
    find_dynamic_menu_for_position,
    get_dynamic_menu_id_for_stack,
)
from ubo_app.store.core.view_registry import (
    get_home_view_data,
    get_registered_dependencies,
)

if TYPE_CHECKING:
    from ubo_app.store.core.types import ViewData
    from ubo_app.store.main import RootState

__all__ = [
    'PAGE_SIZE',
    'compute_view_from_root_state',
    'get_notification_view_data',
    'setup_dynamic_view_autorun',
]

# Re-export PAGE_SIZE for backward compatibility (main __all__ is above)

# Re-export for backward compatibility
_get_dynamic_menu_id_for_stack = get_dynamic_menu_id_for_stack
_find_dynamic_menu_for_position = find_dynamic_menu_for_position


def get_notification_view_data(
    state: RootState,
    notification_id: str,
) -> NotificationViewData:
    """Build NotificationViewData with full notification details from state.

    Args:
        state: The full Redux RootState.
        notification_id: The ID of the notification to look up.

    Returns:
        NotificationViewData with title, content, icon, color, and items populated.

    """
    from ubo_app.store.core.types import MenuItemData

    notification = next(
        (n for n in state.notifications.notifications if n.id == notification_id),
        None,
    )

    if notification:
        # Convert notification actions to MenuItemData
        items: list[MenuItemData | None] = []

        # Add extra_information button if available (shown as info icon on left)
        if notification.extra_information:
            items.append(
                MenuItemData(
                    key='extra_info',
                    label='',
                    icon='󰋼',  # info icon
                    color='#2196F3',
                    is_short=True,
                    action_id=f'notification:extra_info:{notification_id}',
                ),
            )

        # Convert each notification action to MenuItemData
        for i, action in enumerate(notification.actions):
            item_data = item_to_menu_item_data(action, i)
            if item_data is not None:
                # Override action_id to use notification-specific format
                items.append(
                    MenuItemData(
                        key=item_data.key,
                        label=item_data.label,
                        icon=item_data.icon,
                        color=item_data.color,
                        is_short=item_data.is_short,
                        background_color=item_data.background_color,
                        action_id=f'notification:action:{notification_id}:{i}',
                    ),
                )

        # Extract extra information text if available
        extra_info_text = ''
        if notification.extra_information:
            extra_info_text = notification.extra_information.text

        return NotificationViewData(
            notification_id=notification_id,
            title=notification.title,
            content=notification.content,
            icon=notification.icon,
            color=notification.color,
            items=tuple(items),
            extra_information=extra_info_text,
            show_status_bar=False,
        )

    # Fallback if notification not found (edge case)
    return NotificationViewData(
        notification_id=notification_id,
        show_status_bar=False,
    )


def compute_view_from_root_state(state: RootState) -> ViewData:
    """Compute ViewData from the full RootState, using dynamic menus when available.

    This is the dumb UI architecture's view computation function. It checks if
    there's a dynamic menu for the current navigation position, and if so, uses
    its items directly instead of traversing the legacy menu tree.

    Args:
        state: The full Redux RootState.

    Returns:
        ViewData describing what the UI should render.

    """
    main_state = state.main
    dynamic_menus_state = state.dynamic_menus
    stack = main_state.stack

    if not stack:
        return HomeViewData()

    top_item = stack[-1]

    # Handle application views
    if isinstance(top_item, ApplicationStackItem):
        extra_data: dict[str, str] = {}
        for k, v in top_item.initialization_kwargs.items():
            extra_data[k] = str(v)
        return ApplicationViewData(
            application_id=top_item.application_id,
            show_status_bar=False,
            extra_data=extra_data,
        )

    # Handle notification views
    if isinstance(top_item, NotificationStackItem):
        return get_notification_view_data(state, top_item.notification_id)

    # Must be MenuStackItem
    if not isinstance(top_item, MenuStackItem):
        return HomeViewData()

    # Check if we're at home (depth 1)
    depth = len([i for i in stack if isinstance(i, MenuStackItem)])
    if depth <= 1:
        # Home view - get menu items from the root menu
        # Use registry to get home view data from services
        home_data = get_home_view_data(state)
        cpu_percent = home_data.get('cpu_percent', 0.0)
        ram_percent = home_data.get('ram_percent', 0.0)
        volume_level = home_data.get('volume_level', 0.0)

        # Get menu items from the current menu
        home_items: tuple[object, ...] = ()
        current_menu = get_current_menu_from_stack(main_state.menu, stack)
        if current_menu is not None:
            items = menu_items(current_menu)
            menu_item_data = tuple(
                item_to_menu_item_data(item, i) for i, item in enumerate(items)
            )
            home_items = tuple(item for item in menu_item_data if item is not None)

        return HomeViewData(
            show_status_bar=True,
            menu_items=home_items,  # type: ignore[arg-type]
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
            volume_level=volume_level,
        )

    # Try to find a dynamic menu for the current position
    dynamic_match = _find_dynamic_menu_for_position(
        main_state,
        dynamic_menus_state,
        stack,
    )

    if dynamic_match is not None:
        menu_id, title = dynamic_match
        dynamic_menu = dynamic_menus_state.menus.get(menu_id)
        if dynamic_menu:
            items = dynamic_menu.items
            page_index = top_item.page_index
            total_pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)

            return MenuViewData(
                show_status_bar=page_index == 0,
                title=title,
                items=items,
                page_index=page_index,
                total_pages=total_pages,
            )

    # Fall back to legacy view computation from main reducer
    from ubo_app.store.core.reducer import compute_view_from_stack

    return compute_view_from_stack(main_state)


def setup_dynamic_view_autorun() -> None:
    """Set up an autorun to update current_view and status_bar when state changes.

    This should be called after the store is initialized. It watches for
    changes to dynamic_menus, navigation stack, and status bar data, then
    dispatches UpdateCurrentViewAction with the computed view and status bar.
    """
    from redux import AutorunOptions

    from ubo_app.menu_app.view_renderer import compute_status_bar_data
    from ubo_app.store.core.types import UpdateCurrentViewAction
    from ubo_app.store.main import store

    @store.with_state(lambda state: state)
    def _compute_and_dispatch_view(state: RootState) -> None:
        """Compute view and status bar, then dispatch if changed."""
        logger.debug(
            'view_computation: autorun triggered, path=%s',
            list(state.main.path),
        )

        computed_view = compute_view_from_root_state(state)
        computed_status_bar = compute_status_bar_data(state)

        view_changed = state.main.current_view != computed_view
        status_bar_changed = state.main.status_bar != computed_status_bar

        # Only dispatch if view or status bar actually changed
        if view_changed or status_bar_changed:
            logger.debug(
                'view_computation: dispatching update '
                '(view_changed=%s, status_bar_changed=%s)',
                view_changed,
                status_bar_changed,
            )
            store.dispatch(
                UpdateCurrentViewAction(
                    view=computed_view,
                    status_bar=computed_status_bar,
                ),
            )

    @store.autorun(
        lambda state: (
            # Core state (always needed)
            state.main.stack,
            tuple(state.dynamic_menus.menus.keys()),
            # Also watch for menu content changes
            tuple(
                (k, m.items) for k, m in state.dynamic_menus.menus.items()
            ),
            state.main.is_recording,
            state.main.is_replaying,
            # Watch for notification content changes (for progress updates, etc.)
            tuple(
                (n.id, n.title, n.content, n.icon, n.color, n.progress)
                for n in state.notifications.notifications
            ),
            # Dynamic dependencies from registry (menu content only)
            get_registered_dependencies(state),
        ),
        options=AutorunOptions(default_value=None),
    )
    def update_current_view_on_dynamic_change(
        _: tuple | None,
    ) -> None:
        """Update current_view when stack, dynamic menus, or status bar data change."""
        _compute_and_dispatch_view()
