"""View dependency registry for decoupled view updates.

Services register selectors for state that affects view rendering.
Core builds its autorun selector dynamically from registrations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.main import RootState


@dataclass
class ViewRegistry:
    """Registry for view dependencies and path matchers.

    This class holds all registered selectors, path matchers, and providers.
    A singleton instance is created lazily and stored in a container to avoid
    explicit global variable reassignment.
    """

    # View dependency selectors
    status_bar_selectors: dict[str, Callable[[RootState], Any]] = field(
        default_factory=dict,
    )
    home_view_selectors: dict[str, Callable[[RootState], Any]] = field(
        default_factory=dict,
    )
    menu_content_selectors: dict[str, Callable[[RootState], Any]] = field(
        default_factory=dict,
    )

    # Path matchers: matcher_id -> (priority, matcher_func)
    path_menu_matchers: dict[
        str,
        tuple[int, Callable[[tuple[str, ...]], str | None]],
    ] = field(default_factory=dict)

    # Apps menu title (default: 'Apps')
    apps_menu_title: str = 'Apps'

    # Home view data providers
    home_view_data_providers: dict[
        str,
        Callable[[RootState], tuple[str, Any]],
    ] = field(default_factory=dict)

    # Category icons: category_key -> icon
    category_icons: dict[str, str] = field(default_factory=dict)


# Container for lazy singleton initialization (avoids global reassignment)
_registry_container: list[ViewRegistry | None] = [None]


def _get_registry() -> ViewRegistry:
    """Get the view registry singleton.

    The registry is created lazily on first access and stored in a container
    to avoid using `global` keyword for reassignment.
    """
    if _registry_container[0] is None:
        _registry_container[0] = ViewRegistry()
    return _registry_container[0]


# =============================================================================
# View Dependency Selectors
# =============================================================================


def register_status_bar_dependency(
    dependency_id: str,
    selector: Callable[[RootState], Any],
) -> Callable[[], None]:
    """Register a selector that affects status bar content.

    Args:
        dependency_id: Unique identifier for this dependency (e.g., 'system:clock').
        selector: Function that extracts relevant state for view updates.

    Returns:
        Unregister function that removes this dependency when called.

    """
    registry = _get_registry()
    registry.status_bar_selectors[dependency_id] = selector

    def unregister() -> None:
        registry.status_bar_selectors.pop(dependency_id, None)

    return unregister


def register_home_view_dependency(
    dependency_id: str,
    selector: Callable[[RootState], Any],
) -> Callable[[], None]:
    """Register a selector that affects home view content.

    Args:
        dependency_id: Unique identifier for this dependency (e.g., 'system:cpu').
        selector: Function that extracts relevant state for view updates.

    Returns:
        Unregister function that removes this dependency when called.

    """
    registry = _get_registry()
    registry.home_view_selectors[dependency_id] = selector

    def unregister() -> None:
        registry.home_view_selectors.pop(dependency_id, None)

    return unregister


def register_menu_content_dependency(
    dependency_id: str,
    selector: Callable[[RootState], Any],
) -> Callable[[], None]:
    """Register a selector that affects menu content.

    Use for state like assistant engine selections that affect menu item rendering.

    Args:
        dependency_id: Unique identifier for this dependency (e.g., 'assistant:stt').
        selector: Function that extracts relevant state for view updates.

    Returns:
        Unregister function that removes this dependency when called.

    """
    registry = _get_registry()
    registry.menu_content_selectors[dependency_id] = selector

    def unregister() -> None:
        registry.menu_content_selectors.pop(dependency_id, None)

    return unregister


def get_registered_dependencies(state: RootState) -> tuple[Any, ...]:
    """Get registered dependency values for view computation.

    This function is called by the view computation autorun to build a tuple
    of dependency values that affect which view to show. When any value changes,
    the autorun will re-run and recompute the view.

    Note: The following are intentionally excluded:
    - status_bar_selectors: contain frequently-changing values (clock) that
      only affect status bar rendering, not view computation
    - home_view_selectors: contain CPU/RAM metrics that change every second
      but only affect home page gauge rendering, not view selection

    Args:
        state: The current RootState.

    Returns:
        Tuple of all registered view dependency values.

    """
    registry = _get_registry()
    results: list[Any] = []
    # Only menu_content_selectors affect view computation
    for selector in registry.menu_content_selectors.values():
        try:
            results.append(selector(state))
        except (AttributeError, KeyError):
            results.append(None)
    return tuple(results)


# =============================================================================
# Path Menu Matchers
# =============================================================================


def register_path_menu_matcher(
    matcher_id: str,
    matcher: Callable[[tuple[str, ...]], str | None],
    *,
    priority: int = 0,
) -> Callable[[], None]:
    """Register a path-to-menu-id matcher.

    Matchers take a navigation path and return a dynamic menu ID if they match.
    This allows services and the application to register their own path parsing
    logic without hardcoding it in the core.

    Args:
        matcher_id: Unique identifier for this matcher (e.g., 'docker:apps').
        matcher: Function that takes path tuple and returns menu_id or None.
        priority: Higher priority matchers are tried first. Default is 0.

    Returns:
        Unregister function that removes this matcher when called.

    """
    registry = _get_registry()
    registry.path_menu_matchers[matcher_id] = (priority, matcher)

    def unregister() -> None:
        registry.path_menu_matchers.pop(matcher_id, None)

    return unregister


def get_menu_id_for_path(path: tuple[str, ...]) -> str | None:
    """Try all registered matchers to get menu ID from path.

    Matchers are tried in priority order (highest first).
    The first matcher that returns a non-None value wins.

    Args:
        path: The navigation path tuple.

    Returns:
        The menu ID if any matcher matches, None otherwise.

    """
    registry = _get_registry()
    # Sort by priority descending
    sorted_matchers = sorted(
        registry.path_menu_matchers.values(),
        key=lambda x: x[0],
        reverse=True,
    )
    for _priority, matcher in sorted_matchers:
        result = matcher(path)
        if result is not None:
            return result
    return None


# =============================================================================
# Apps Menu Title
# =============================================================================


def register_apps_menu_title(title: str) -> Callable[[], None]:
    """Register the apps menu title.

    This allows services to customize the apps menu title.
    The last registration wins (typically there's only one).

    Args:
        title: The title for the apps menu.

    Returns:
        Unregister function that resets to default when called.

    """
    registry = _get_registry()
    registry.apps_menu_title = title

    def unregister() -> None:
        registry.apps_menu_title = 'Apps'

    return unregister


def get_apps_menu_title() -> str:
    """Get registered apps menu title.

    Returns:
        The registered title, or 'Apps' as default.

    """
    return _get_registry().apps_menu_title


# =============================================================================
# Home View Data Providers
# =============================================================================


def register_home_view_data_provider(
    provider_id: str,
    provider: Callable[[RootState], tuple[str, Any]],
) -> Callable[[], None]:
    """Register a home view data provider.

    Providers extract key-value pairs from state for the home view.
    This allows services to register their own data (e.g., CPU, RAM, volume)
    instead of hardcoding access in the core.

    Args:
        provider_id: Unique identifier for this provider (e.g., 'system:cpu').
        provider: Function that returns (key, value) tuple from state.

    Returns:
        Unregister function that removes this provider when called.

    """
    registry = _get_registry()
    registry.home_view_data_providers[provider_id] = provider

    def unregister() -> None:
        registry.home_view_data_providers.pop(provider_id, None)

    return unregister


def get_home_view_data(state: RootState) -> dict[str, Any]:
    """Collect all home view data from registered providers.

    Args:
        state: The current RootState.

    Returns:
        Dictionary with all provider key-value pairs.

    """
    registry = _get_registry()
    result: dict[str, Any] = {}
    for provider in registry.home_view_data_providers.values():
        try:
            key, value = provider(state)
            result[key] = value
        except (AttributeError, KeyError):
            pass
    return result


# =============================================================================
# Category Icons
# =============================================================================


def register_category_icon(
    category_key: str,
    icon: str,
) -> Callable[[], None]:
    """Register an icon for a category.

    This allows applications to register icons for settings categories
    or other categorized menus without hardcoding them in the core.

    Args:
        category_key: The category identifier (e.g., 'Network', 'Docker').
        icon: The icon string (e.g., nerd font icon).

    Returns:
        Unregister function that removes this icon when called.

    """
    registry = _get_registry()
    registry.category_icons[category_key] = icon

    def unregister() -> None:
        registry.category_icons.pop(category_key, None)

    return unregister


def get_category_icon(category_key: str, default: str = '') -> str:
    """Get registered icon for a category.

    Args:
        category_key: The category identifier.
        default: Default icon if not registered.

    Returns:
        The registered icon, or default if not found.

    """
    return _get_registry().category_icons.get(category_key, default)
