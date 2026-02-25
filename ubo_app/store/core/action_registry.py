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

from ubo_app.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable

# Global registry mapping action_id -> handler function
_action_handlers: dict[str, Callable[[], object]] = {}


def register_action(
    action_id: str,
    handler: Callable[[], object],
) -> Callable[[], object]:
    """Register an action handler for a given action_id.

    Args:
        action_id: Unique identifier for the action (e.g., 'wifi:connect:MyNetwork').
        handler: Callable to invoke when the action is executed.

    Returns:
        The handler function (for chaining/decorator use).

    Raises:
        ValueError: If an action with the same ID is already registered.

    """
    if action_id in _action_handlers:
        msg = f"Action '{action_id}' is already registered"
        raise ValueError(msg)
    _action_handlers[action_id] = handler
    logger.debug('Registered action handler: %s', action_id)
    return handler


def unregister_action(action_id: str) -> bool:
    """Unregister an action handler.

    Args:
        action_id: The action ID to unregister.

    Returns:
        True if the action was found and removed, False otherwise.

    """
    if action_id in _action_handlers:
        del _action_handlers[action_id]
        logger.debug('Unregistered action handler: %s', action_id)
        return True
    return False


def execute_action(action_id: str) -> object:
    """Execute the handler for an action_id.

    Args:
        action_id: The action ID to execute.

    Returns:
        The handler's return value, or None if not found or on error.
        Handlers that return Menu objects signal that a sub-menu should be
        pushed onto the navigation stack.

    """
    handler = _action_handlers.get(action_id)
    if handler is not None:
        logger.debug('Executing action: %s', action_id)
        try:
            return handler()
        except Exception:
            logger.exception('Error executing action: %s', action_id)
            return None
    logger.warning('No handler registered for action: %s', action_id)
    return None


def get_registered_actions() -> list[str]:
    """Get list of all registered action IDs.

    Returns:
        List of registered action ID strings.

    """
    return list(_action_handlers.keys())


def clear_all_actions() -> None:
    """Clear all registered actions.

    Primarily useful for testing.
    """
    _action_handlers.clear()
    logger.debug('Cleared all action handlers')
