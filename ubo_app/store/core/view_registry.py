"""View dependency registry for decoupled view updates.

Services register selectors for state that affects view rendering.
Core builds its autorun selector dynamically from registrations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.main import RootState

# Registries for different view contexts
_status_bar_selectors: dict[str, Callable[[RootState], Any]] = {}
_home_view_selectors: dict[str, Callable[[RootState], Any]] = {}
_menu_content_selectors: dict[str, Callable[[RootState], Any]] = {}


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
    _status_bar_selectors[dependency_id] = selector

    def unregister() -> None:
        _status_bar_selectors.pop(dependency_id, None)

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
    _home_view_selectors[dependency_id] = selector

    def unregister() -> None:
        _home_view_selectors.pop(dependency_id, None)

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
    _menu_content_selectors[dependency_id] = selector

    def unregister() -> None:
        _menu_content_selectors.pop(dependency_id, None)

    return unregister


def get_registered_dependencies(state: RootState) -> tuple[Any, ...]:
    """Get all registered dependency values for the autorun selector.

    This function is called by the view computation autorun to build a tuple
    of all registered dependency values. When any value changes, the autorun
    will re-run and recompute the view.

    Args:
        state: The current RootState.

    Returns:
        Tuple of all registered dependency values.

    """
    results: list[Any] = []
    for selector in _status_bar_selectors.values():
        try:
            results.append(selector(state))
        except (AttributeError, KeyError):
            results.append(None)
    for selector in _home_view_selectors.values():
        try:
            results.append(selector(state))
        except (AttributeError, KeyError):
            results.append(None)
    for selector in _menu_content_selectors.values():
        try:
            results.append(selector(state))
        except (AttributeError, KeyError):
            results.append(None)
    return tuple(results)
