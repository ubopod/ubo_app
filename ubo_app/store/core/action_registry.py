"""Action handler registry for executing menu actions by action_id.

This module provides infrastructure for services to register action handlers
that can be executed when the user selects a menu item in the dumb UI architecture.

Services register handlers like:
    register_action('wifi:connect:MyNetwork', lambda: connect_to_wifi('MyNetwork'))

When the UI dispatches ExecuteMenuActionAction(action_id='wifi:connect:MyNetwork'),
the reducer calls execute_action() which invokes the registered handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.handler_registry import HandlerRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

# Singleton action registry instance
_registry = HandlerRegistry('action')


def register_action(
    action_id: str,
    handler: Callable[[], object],
    *,
    allow_reregister: bool = False,
) -> Callable[[], object]:
    """Register an action handler for a given action_id.

    Args:
        action_id: Unique identifier for the action (e.g., 'wifi:connect:MyNetwork').
        handler: Callable to invoke when the action is executed.
        allow_reregister: If True, silently replaces an existing handler
            with the same ID. If False (default), raises ValueError.

    Returns:
        The handler function (for chaining/decorator use).

    Raises:
        ValueError: If an action with the same ID is already registered
            and allow_reregister is False.

    """
    return _registry.register(action_id, handler, allow_reregister=allow_reregister)


def unregister_action(action_id: str) -> bool:
    """Unregister an action handler.

    Args:
        action_id: The action ID to unregister.

    Returns:
        True if the action was found and removed, False otherwise.

    """
    return _registry.unregister(action_id)


def get_action(action_id: str) -> Callable[[], object] | None:
    """Get the handler for an action_id without executing it.

    Args:
        action_id: The action ID to look up.

    Returns:
        The handler callable, or None if not found.

    """
    return _registry.get(action_id)


def execute_action(action_id: str) -> object:
    """Execute the handler for an action_id.

    Args:
        action_id: The action ID to execute.

    Returns:
        The handler's return value, or None if not found or on error.
        Handlers that return Menu objects signal that a sub-menu should be
        pushed onto the navigation stack.

    """
    _, result = _registry.execute(action_id)
    return result


def get_registered_actions() -> list[str]:
    """Get list of all registered action IDs.

    Returns:
        List of registered action ID strings.

    """
    return _registry.get_registered_ids()


def clear_all_actions() -> None:
    """Clear all registered actions.

    Primarily useful for testing.
    """
    _registry.clear()
