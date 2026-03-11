"""View computation utilities for the dumb UI architecture.

This module provides functions to compute ViewData from the full RootState,
using dynamic menus exclusively. It can be used by both GUI (Kivy) and
non-GUI contexts (gRPC/TUI).
"""

from __future__ import annotations

import math
import socket
from typing import TYPE_CHECKING

from ubo_app.constants import DEBUG_MENU
from ubo_app.logger import logger
from ubo_app.store.core.constants import (
    NOTIFICATION_ACTION_PREFIX,
    NOTIFICATION_DISMISS_PREFIX,
    NOTIFICATION_EXTRA_INFO_PREFIX,
    PAGE_SIZE,
    compute_total_pages,
)
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
from ubo_app.store.core.view_helpers import find_dynamic_menu_for_position
from ubo_app.store.core.view_registry import (
    get_home_view_data,
    get_registered_dependencies,
    get_registered_status_bar_dependencies,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.core.types import ViewData
    from ubo_app.store.main import RootState

# Cache hostname at module load — it doesn't change at runtime
_HOSTNAME_TITLE = f'󰋜{socket.gethostname()}.local'

__all__ = [
    'PAGE_SIZE',
    'compute_status_bar_data',
    'compute_view_from_root_state',
    'get_notification_view_data',
    'release_view_autorun',
    'setup_dynamic_view_autorun',
    'suppress_view_autorun',
]

# Gate to suppress redundant view computations during startup (service
# reducer registration burst).  When suppressed, autorun callbacks mark
# dirty instead of computing immediately.  On release, a single
# computation runs if dirty.
# Container pattern (list singletons) avoids ``global`` statements.
_suppressed: list[bool] = [False]
_dirty: list[bool] = [False]
_dispatch_fn: list[Callable[[], None] | None] = [None]


def suppress_view_autorun() -> None:
    """Suppress view autorun during startup (e.g. service registration)."""
    _suppressed[0] = True


def release_view_autorun() -> None:
    """Release the startup gate and run one deferred computation if needed."""
    _suppressed[0] = False
    if _dirty[0] and _dispatch_fn[0] is not None:
        _dirty[0] = False
        _dispatch_fn[0]()



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
                    color='#ffffff',
                    is_short=True,
                    action_id=f'{NOTIFICATION_EXTRA_INFO_PREFIX}{notification_id}',
                ),
            )

        # Convert each notification action to MenuItemData
        # Notification items are always is_short=True (compact icon buttons)
        for i, action in enumerate(notification.actions):
            bg_color = (
                action.background_color
                if isinstance(action.background_color, str)
                else None
            )
            items.append(
                MenuItemData(
                    key=action.key or f'action_{i}',
                    label=action.label,
                    icon=action.icon,
                    color=action.color,
                    is_short=True,
                    background_color=bg_color,
                    action_id=f'{NOTIFICATION_ACTION_PREFIX}{notification_id}:{i}',
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
                    action_id=f'{NOTIFICATION_DISMISS_PREFIX}{notification_id}',
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
    if hasattr(state, 'notifications') and state.notifications.notifications:
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
    if hasattr(state, 'status_icons') and state.status_icons.icons is not None:
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
    if hasattr(state, 'sensors'):
        temperature = getattr(
            getattr(state.sensors, 'temperature', None), 'value', None,
        )
        light_level = getattr(
            getattr(state.sensors, 'light', None), 'value', None,
        )

    # Get system metrics (clock)
    clock = getattr(getattr(state, 'system', None), 'clock', '') or ''

    # Get recording states (main is always present)
    is_recording = state.main.is_recording
    is_replaying = state.main.is_replaying
    is_recording_audio = getattr(
        getattr(state, 'audio', None), 'is_recording', False,
    )

    return StatusBarData(
        title=_HOSTNAME_TITLE,
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
        return ApplicationViewData(
            application_id=top_item.application_id,
            show_status_bar=False,
            extra_data=dict(top_item.initialization_kwargs),
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
    dynamic_match = find_dynamic_menu_for_position(
        main_state,
        dynamic_menus_state,
        stack,
    )

    if dynamic_match is not None:
        menu_id, title = dynamic_match
        dynamic_menu = dynamic_menus_state.menus.get(menu_id)
        if dynamic_menu:
            items = dynamic_menu.items
            total_pages = compute_total_pages(
                len(items),
                is_headed=dynamic_menu.heading is not None,
            )
            # Clamp page_index to valid range in case dynamic menu
            # items changed and the old page_index is now out of bounds.
            page_index = min(top_item.page_index, max(total_pages - 1, 0))

            return MenuViewData(
                show_status_bar=page_index == 0,
                title=title,
                heading=dynamic_menu.heading,
                sub_heading=dynamic_menu.sub_heading,
                items=items,
                placeholder=dynamic_menu.placeholder or None,
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


def _dispatch_view_update(state: RootState) -> None:
    """Compute view and status bar, then dispatch if changed."""
    from ubo_app.store.core.types import UpdateCurrentViewAction
    from ubo_app.store.main import store

    computed_view = compute_view_from_root_state(state)
    computed_status_bar = compute_status_bar_data(state)

    view_changed = state.main.current_view != computed_view
    status_bar_changed = state.main.status_bar != computed_status_bar

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


def _dispatch_status_bar_update(state: RootState) -> None:
    """Compute status bar (and home view if visible), dispatch if changed."""
    from ubo_app.store.core.types import UpdateCurrentViewAction
    from ubo_app.store.main import store

    computed_status_bar = compute_status_bar_data(state)
    status_bar_changed = state.main.status_bar != computed_status_bar

    # When on the home screen, CPU/RAM/volume gauges are part of the
    # view, not just the status bar - recompute the view too.
    current_view = state.main.current_view
    view_changed = False
    computed_view = current_view
    if isinstance(current_view, HomeViewData):
        computed_view = compute_view_from_root_state(state)
        view_changed = current_view != computed_view

    if view_changed or status_bar_changed:
        logger.debug(
            'view_computation: status-bar autorun dispatching '
            '(view_changed=%s, status_bar_changed=%s)',
            view_changed,
            status_bar_changed,
        )
        store.dispatch(
            UpdateCurrentViewAction(
                view=computed_view or HomeViewData(),
                status_bar=computed_status_bar,
            ),
        )


def setup_dynamic_view_autorun() -> None:
    """Set up autoruns to update current_view and status_bar when state changes.

    This should be called after the store is initialized.  Two autoruns are
    created to separate concerns:

    1. **View autorun** - watches navigation stack, dynamic menus,
       notifications, and registered apps.  Fires infrequently (on user
       interaction / service registration).

    2. **Status-bar autorun** - watches home-view data (CPU, RAM, volume)
       and status-bar dependencies (clock, temperature, icons).  Fires more
       often but only recomputes status bar data (cheap).
    """
    from redux import AutorunOptions

    from ubo_app.store.main import store

    @store.with_state(lambda state: state)
    def _view_dispatch(state: RootState) -> None:
        _dispatch_view_update(state)

    @store.with_state(lambda state: state)
    def _status_bar_dispatch(state: RootState) -> None:
        _dispatch_status_bar_update(state)

    # Store reference so release_view_autorun() can trigger a computation
    _dispatch_fn[0] = _view_dispatch

    # -- View autorun (infrequent) ------------------------------------------

    @store.autorun(
        lambda state: (
            state.main.stack,
            state.dynamic_menus.version,
            state.main.is_recording,
            state.main.is_replaying,
            tuple(state.main.registered_apps.keys()),
            tuple(
                (n.id, n.title, n.content, n.icon, n.color, n.progress)
                for n in state.notifications.notifications
            ),
            get_registered_dependencies(state),
        ),
        options=AutorunOptions(default_value=None),
    )
    def _update_view_on_navigation_change(_: tuple | None) -> None:
        """Update current_view when stack, dynamic menus, etc. change."""
        if _suppressed[0]:
            _dirty[0] = True
            return
        _view_dispatch()  # type: ignore[call-arg]

    # -- Status-bar autorun (frequent but cheap) ----------------------------

    @store.autorun(
        lambda state: (
            get_home_view_data(state),
            get_registered_status_bar_dependencies(state),
        ),
        options=AutorunOptions(default_value=None),
    )
    def _update_status_bar_on_metrics_change(_: tuple | None) -> None:
        """Update status bar when metrics / clock / icons change."""
        if _suppressed[0]:
            return
        _status_bar_dispatch()  # type: ignore[call-arg]
