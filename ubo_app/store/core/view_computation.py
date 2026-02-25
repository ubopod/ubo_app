"""View computation utilities for the dumb UI architecture.

This module provides functions to compute ViewData from the full RootState,
using dynamic menus exclusively. It can be used by both GUI (Kivy) and
non-GUI contexts (gRPC/TUI).
"""

from __future__ import annotations

import contextlib
import math
from typing import TYPE_CHECKING

from ubo_app.constants import DEBUG_MENU
from ubo_app.logger import logger
from ubo_app.store.core.constants import PAGE_SIZE, compute_total_pages
from ubo_app.store.core.menu_adapter import item_to_menu_item_data
from ubo_app.store.core.types import (
    ApplicationStackItem,
    ApplicationViewData,
    HomeViewData,
    MenuStackItem,
    MenuViewData,
    NotificationStackItem,
    NotificationViewData,
    ProgressNotificationData,
    StatusBarData,
    StatusIconData,
)
from ubo_app.store.core.view_helpers import (
    find_dynamic_menu_for_position,
    get_dynamic_menu_id_for_stack,
)
from ubo_app.store.core.view_registry import (
    get_home_view_data,
    get_registered_dependencies,
    get_registered_status_bar_dependencies,
)

if TYPE_CHECKING:
    from ubo_app.store.core.types import ViewData
    from ubo_app.store.main import RootState

__all__ = [
    'PAGE_SIZE',
    'compute_status_bar_data',
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

    notification = None
    if hasattr(state, 'notifications'):
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
                    icon='\U000f02fc',  # info icon
                    color='#2196F3',
                    is_short=True,
                    action_id=f'notification:extra_info:{notification_id}',
                ),
            )

        # Convert each notification action to MenuItemData
        # Notification items are always is_short=True (compact icon buttons)
        for i, action in enumerate(notification.actions):
            item_data = item_to_menu_item_data(action, i)
            if item_data is not None:
                # Override action_id and force is_short for notification layout
                items.append(
                    MenuItemData(
                        key=item_data.key,
                        label=item_data.label,
                        icon=item_data.icon,
                        color=item_data.color,
                        is_short=True,
                        background_color=item_data.background_color,
                        action_id=f'notification:action:{notification_id}:{i}',
                    ),
                )

        # Add dismiss button at the bottom if show_dismiss_action is True
        show_dismiss = getattr(notification, 'show_dismiss_action', True)
        if show_dismiss:
            items.append(
                MenuItemData(
                    key='dismiss',
                    label='',
                    icon='\uf00d',  # close/X icon
                    color='#ffffff',
                    is_short=True,
                    background_color='#C0C0C0',
                    action_id=f'notification:dismiss:{notification_id}',
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


def compute_status_bar_data(state: RootState) -> StatusBarData:
    """Compute StatusBarData from the full Redux state.

    This consolidates all status bar information from various state slices
    into a single serializable object.
    """
    # Compute progress notifications from notifications with progress
    progress_notifications: list[ProgressNotificationData] = []
    with contextlib.suppress(AttributeError, TypeError):
        progress_notifications = [
            ProgressNotificationData(
                id=notification.id,
                progress=(
                    None
                    if math.isnan(notification.progress)
                    else notification.progress
                ),
                color=notification.color,
            )
            for notification in state.notifications.notifications
            if notification.progress is not None
        ]

    # Compute icons from status_icons state
    icons: tuple[StatusIconData, ...] = ()
    try:
        icons = tuple(
            StatusIconData(symbol=icon.symbol, color=icon.color)
            for icon in state.status_icons.icons
        )
    except (AttributeError, TypeError) as e:
        if DEBUG_MENU:
            logger.warning('[ViewRenderer] Failed to compute icons: %s', e)

    # Get temperature and light from sensors
    temperature: float | None = None
    light_level: float | None = None
    with contextlib.suppress(AttributeError, TypeError):
        temperature = state.sensors.temperature.value
        light_level = state.sensors.light.value

    # Get system metrics (clock)
    clock = ''
    with contextlib.suppress(AttributeError, TypeError):
        clock = state.system.clock

    # Get recording states
    is_recording = False
    is_replaying = False
    is_recording_audio = False
    with contextlib.suppress(AttributeError, TypeError):
        is_recording = state.main.is_recording
        is_replaying = state.main.is_replaying
    with contextlib.suppress(AttributeError, TypeError):
        is_recording_audio = state.audio.is_recording

    # Title shows hostname (previously from legacy HOME_MENU.title)
    import socket

    title = f'󰋜{socket.gethostname()}.local'

    return StatusBarData(
        title=title,
        is_recording=is_recording,
        is_replaying=is_replaying,
        is_recording_audio=is_recording_audio,
        progress_notifications=tuple(progress_notifications),
        clock=clock,
        temperature=temperature,
        light_level=light_level,
        icons=icons,
    )


def compute_view_from_root_state(state: RootState) -> ViewData:
    """Compute ViewData from the full RootState, using dynamic menus.

    This is the dumb UI architecture's view computation function. It uses
    dynamic menus exclusively for all menu views.

    Args:
        state: The full Redux RootState.

    Returns:
        ViewData describing what the UI should render.

    """
    from ubo_app.store.core.menus import HOME_MENU_ID

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
        # Home view - get items from the HOME_MENU_ID dynamic menu
        home_data = get_home_view_data(state)
        cpu_percent = home_data.get('cpu_percent', 0.0)
        ram_percent = home_data.get('ram_percent', 0.0)
        volume_level = home_data.get('volume_level', 0.0)

        from ubo_app.store.core.types import MenuItemData

        home_items: tuple[MenuItemData, ...] = ()
        home_menu = dynamic_menus_state.menus.get(HOME_MENU_ID)
        if home_menu is not None:
            home_items = tuple(
                item for item in home_menu.items if item is not None
            )

        return HomeViewData(
            show_status_bar=True,
            menu_items=home_items,
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
            total_pages = compute_total_pages(
                len(items),
                is_headed=dynamic_menu.heading is not None,
            )

            return MenuViewData(
                show_status_bar=page_index == 0,
                title=title,
                heading=dynamic_menu.heading,
                sub_heading=dynamic_menu.sub_heading,
                items=items,
                page_index=page_index,
                total_pages=total_pages,
            )

    # No dynamic menu found - return empty menu view
    return MenuViewData(
        show_status_bar=True,
        title='',
        items=(),
        page_index=0,
        total_pages=1,
    )


def setup_dynamic_view_autorun() -> None:
    """Set up an autorun to update current_view and status_bar when state changes.

    This should be called after the store is initialized. It watches for
    changes to dynamic_menus, navigation stack, and status bar data, then
    dispatches UpdateCurrentViewAction with the computed view and status bar.
    """
    from redux import AutorunOptions

    from ubo_app.store.core.types import UpdateCurrentViewAction
    from ubo_app.store.main import store

    @store.with_state(lambda state: state)
    def _compute_and_dispatch_view(state: RootState) -> None:
        """Compute view and status bar, then dispatch if changed."""
        logger.debug(
            'view_computation: autorun triggered, stack_len=%d',
            len(state.main.stack),
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
            # Watch registered_apps for dynamic menu updates from registrations
            tuple(state.main.registered_apps.items()),
            # Watch for notification content changes (for progress updates, etc.)
            tuple(
                (n.id, n.title, n.content, n.icon, n.color, n.progress)
                for n in state.notifications.notifications
            ),
            # Dynamic dependencies from registry (menu content only)
            get_registered_dependencies(state),
            # Home view data (volume, CPU, RAM) and status bar data (clock,
            # temperature, icons) -- needed for gRPC GUI clients that rely on
            # current_view for all rendering
            get_home_view_data(state),
            get_registered_status_bar_dependencies(state),
        ),
        options=AutorunOptions(default_value=None),
    )
    def update_current_view_on_dynamic_change(
        _: tuple | None,
    ) -> None:
        """Update current_view when stack, dynamic menus, or status bar data change."""
        _compute_and_dispatch_view()
