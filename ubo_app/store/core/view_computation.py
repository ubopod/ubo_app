"""View computation utilities for the dumb UI architecture.

This module provides functions to compute ViewData from the full RootState,
including support for dynamic menus. It can be used by both GUI (Kivy) and
non-GUI contexts (gRPC/TUI).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    ApplicationStackItem,
    ApplicationViewData,
    HomeViewData,
    MenuStackItem,
    MenuViewData,
    NotificationStackItem,
    NotificationViewData,
)

if TYPE_CHECKING:
    from ubo_app.store.core.types import DynamicMenusState, MainState, ViewData
    from ubo_app.store.main import RootState


def _get_dynamic_menu_id_for_stack(
    main_state: MainState,
) -> str | None:
    """Determine which dynamic menu ID corresponds to the current stack position.

    This maps the navigation path to a dynamic menu ID. Services register their
    menus with IDs like 'docker:image:envoy', 'wifi:connections', etc.

    Returns None if no matching dynamic menu ID can be determined.
    """
    path = list(main_state.path)
    if not path:
        return None

    # Direct path-to-menu mappings for known paths
    path_mappings: dict[tuple[str, ...], str] = {
        # Core menus
        ('main',): 'main:menu',
        ('main', 'apps'): 'apps:list',
        ('main', 'settings'): 'settings:categories',
        ('notifications',): 'notifications:list',
        ('power',): 'power:options',
    }

    # Check exact path matches first
    path_tuple = tuple(path)
    if path_tuple in path_mappings:
        return path_mappings[path_tuple]

    # Docker app menus: path is ['main', 'apps', 'docker_image_id:']
    if len(path) >= 3 and path[:2] == ['main', 'apps']:  # noqa: PLR2004
        app_key = path[2]
        # Check if this is a Docker image (key ends with ':' from service prefix)
        if ':' in app_key:
            # Extract the image_id from the key (e.g., 'envoy' from '080-docker:envoy')
            image_id = app_key.split(':')[-1]
            if image_id:
                return f'docker:image:{image_id}'

    # Settings -> Category -> Service mappings
    if len(path) >= 4 and path[:2] == ['main', 'settings']:  # noqa: PLR2004
        service_key = path[3]  # e.g., '000-display:', '010-speech-synthesis:engines'

        # Map service prefixes to their dynamic menu IDs
        # Format: (service_prefix, key_suffix) -> menu_id
        settings_menu_mappings: dict[tuple[str, str], str] = {
            # Display service
            ('000-display', ''): 'display:timeout',
            # Speech synthesis service
            ('010-speech-synthesis', 'engines'): 'speech-synthesis:main',
            ('010-speech-synthesis', 'settings'): 'speech-synthesis:picovoice',
            # Docker setup
            ('080-docker', 'service'): 'docker:setup',
            ('080-docker', 'registries'): 'docker:registries',
        }

        if ':' in service_key:
            parts = service_key.split(':')
            service_prefix = parts[0]
            key_suffix = parts[1] if len(parts) > 1 else ''

            # Check for specific mapping first
            mapping_key = (service_prefix, key_suffix)
            if mapping_key in settings_menu_mappings:
                return settings_menu_mappings[mapping_key]

            # Fall back to generic service:main pattern
            # Extract short service name (strip numeric prefix like '030-')
            short_name = service_prefix.lstrip('0123456789-')
            if short_name:
                return f'{short_name}:main'

    return None


def _find_dynamic_menu_by_title(
    title: str,
    dynamic_menus_state: DynamicMenusState,
) -> str | None:
    """Find a dynamic menu ID by matching the menu title.

    This is used when path-based mapping fails, as some menus are
    returned by action callbacks and don't appear in the navigation path.

    Args:
        title: The menu title to search for.
        dynamic_menus_state: The dynamic menus state.

    Returns:
        The menu_id if found, None otherwise.

    """
    # Normalize title for comparison (some titles have icon prefixes)
    # Strip common nerd font icon prefixes
    clean_title = title.lstrip('󰀁󰀂󰀃󰀄󰀅󰀆󰀇󰀈󰀉󰀊󰀋󰀌󰀍󰀎󰀏󰀐󰀑󰀒󰀓󰀔󰀕󰀖󰀗󰀘󰀙󰀚󰀛󰀜󰀝󰀞󰀟󰡉󱛃󰖩󰨞').strip()

    for menu_id, menu_data in dynamic_menus_state.menus.items():
        menu_title = menu_data.title.lstrip(
            '󰀁󰀂󰀃󰀄󰀅󰀆󰀇󰀈󰀉󰀊󰀋󰀌󰀍󰀎󰀏󰀐󰀑󰀒󰀓󰀔󰀕󰀖󰀗󰀘󰀙󰀚󰀛󰀜󰀝󰀞󰀟󰡉󱛃󰖩󰨞',
        ).strip()
        if clean_title == menu_title:
            return menu_id

    return None


def _find_dynamic_menu_for_position(
    main_state: MainState,
    dynamic_menus_state: DynamicMenusState | None,
    stack: tuple,
) -> tuple[str, str] | None:
    """Find a dynamic menu matching the current navigation position.

    Tries path-based mapping first, then falls back to title-based matching.

    Args:
        main_state: The main state containing navigation path.
        dynamic_menus_state: The dynamic menus state.
        stack: The navigation stack.

    Returns:
        Tuple of (menu_id, title) if found, None otherwise.

    """
    if not dynamic_menus_state:
        return None

    # Try path-based mapping first
    menu_id = _get_dynamic_menu_id_for_stack(main_state)
    if menu_id:
        dynamic_menu = dynamic_menus_state.menus.get(menu_id)
        if dynamic_menu:
            return (menu_id, dynamic_menu.title)

    # Fall back to title-based matching
    if not dynamic_menus_state.menus:
        return None

    # Import here to avoid circular dependency
    from ubo_app.store.core.reducer import get_current_menu_from_stack

    current_menu = get_current_menu_from_stack(main_state.menu, stack)
    if current_menu is None:
        return None

    title_val = current_menu.title
    current_title = str(title_val() if callable(title_val) else (title_val or ''))
    if not current_title:
        return None

    found_menu_id = _find_dynamic_menu_by_title(current_title, dynamic_menus_state)
    if found_menu_id:
        dynamic_menu = dynamic_menus_state.menus.get(found_menu_id)
        if dynamic_menu:
            return (found_menu_id, dynamic_menu.title)

    return None


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
        # Home view doesn't use dynamic menus, it has fixed items
        # Read actual values from state
        cpu_percent = state.system.cpu_percent if hasattr(state, 'system') else 0.0
        ram_percent = state.system.ram_percent if hasattr(state, 'system') else 0.0
        volume_level = state.audio.playback_volume if hasattr(state, 'audio') else 0.0
        return HomeViewData(
            show_status_bar=True,
            menu_items=(),
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
            page_size = 3
            total_pages = max(1, (len(items) + page_size - 1) // page_size)

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
    """Set up an autorun to update current_view when dynamic menus change.

    This should be called after the store is initialized. It watches for
    changes to dynamic_menus and the navigation stack, and dispatches
    UpdateCurrentViewAction with the properly computed view.
    """
    from redux import AutorunOptions

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
        ),
        options=AutorunOptions(default_value=None),
    )
    def update_current_view_on_dynamic_change(
        _: tuple | None,
    ) -> None:
        """Update current_view when stack, dynamic menus, or system metrics change."""
        state = store._state  # noqa: SLF001
        if state is None:
            return

        computed_view = compute_view_from_root_state(state)

        # Only dispatch if view actually changed
        if state.main.current_view != computed_view:
            store.dispatch(UpdateCurrentViewAction(view=computed_view))
