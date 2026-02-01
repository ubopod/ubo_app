"""View computation utilities for the dumb UI architecture.

This module provides functions to compute ViewData from the full RootState,
including support for dynamic menus. It can be used by both GUI (Kivy) and
non-GUI contexts (gRPC/TUI).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_gui.menu.types import menu_items

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

if TYPE_CHECKING:
    from ubo_app.store.core.types import ViewData
    from ubo_app.store.main import RootState

# Re-export PAGE_SIZE for backward compatibility
__all__ = ['PAGE_SIZE', 'compute_view_from_root_state', 'setup_dynamic_view_autorun']

# Re-export for backward compatibility
_get_dynamic_menu_id_for_stack = get_dynamic_menu_id_for_stack
_find_dynamic_menu_for_position = find_dynamic_menu_for_position


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
        return NotificationViewData(
            notification_id=top_item.notification_id,
            show_status_bar=False,
        )

    # Must be MenuStackItem
    if not isinstance(top_item, MenuStackItem):
        return HomeViewData()

    # Check if we're at home (depth 1)
    depth = len([i for i in stack if isinstance(i, MenuStackItem)])
    if depth <= 1:
        # Home view - get menu items from the root menu
        cpu_percent = state.system.cpu_percent if hasattr(state, 'system') else 0.0
        ram_percent = state.system.ram_percent if hasattr(state, 'system') else 0.0
        volume_level = state.audio.playback_volume if hasattr(state, 'audio') else 0.0

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

    @store.autorun(
        lambda state: (
            state.main.stack,
            tuple(state.dynamic_menus.menus.keys()),
            # Also watch for menu content changes
            tuple(
                (k, m.items) for k, m in state.dynamic_menus.menus.items()
            ),
            # Only watch system metrics when on home view to avoid unnecessary updates
            # Stack changes will trigger autorun anyway when navigating to/from home
            (
                state.system.cpu_percent if hasattr(state, 'system') else 0.0,
                state.system.ram_percent if hasattr(state, 'system') else 0.0,
                state.audio.playback_volume if hasattr(state, 'audio') else 0.0,
            )
            if (
                state.main.current_view is not None
                and getattr(state.main.current_view, 'type', None) == 'home'
            )
            else None,
            # Watch status bar dependencies (clock, temperature, icons, recording state)
            state.system.clock if hasattr(state, 'system') else '',
            state.sensors.temperature.value
            if hasattr(state, 'sensors') and state.sensors.temperature
            else None,
            tuple(state.status_icons.icons)
            if hasattr(state, 'status_icons')
            else (),
            state.main.is_recording,
            state.main.is_replaying,
            state.audio.is_recording if hasattr(state, 'audio') else False,
        ),
        options=AutorunOptions(default_value=None),
    )
    def update_current_view_on_dynamic_change(
        _: tuple | None,
    ) -> None:
        """Update current_view when stack, dynamic menus, or status bar data change."""
        state = store._state  # noqa: SLF001
        if state is None:
            return

        computed_view = compute_view_from_root_state(state)
        computed_status_bar = compute_status_bar_data(state)

        # Only dispatch if view or status bar actually changed
        if (
            state.main.current_view != computed_view
            or state.main.status_bar != computed_status_bar
        ):
            store.dispatch(
                UpdateCurrentViewAction(
                    view=computed_view,
                    status_bar=computed_status_bar,
                ),
            )
