"""Callback registry for executing callbacks by ID.

This module provides infrastructure for services to register callback handlers
that can be executed when a notification is closed or other events occur.

Services register handlers like:
    callback_id = register_auto_callback(lambda: cleanup_resources())

When the notification is closed, the handler code calls:
    execute_callback(callback_id)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.handler_registry import HandlerRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

# Singleton callback registry instance
_registry = HandlerRegistry('callback')


def register_callback(callback_id: str, handler: Callable[[], object]) -> str:
    """Register a callback handler for a given callback_id.

    Args:
        callback_id: Unique identifier for the callback.
        handler: Callable to invoke when the callback is executed.

    Returns:
        The callback_id (for convenience).

    Raises:
        ValueError: If a callback with the same ID is already registered.

    """
    _registry.register(callback_id, handler)
    return callback_id


def register_auto_callback(handler: Callable[[], object]) -> str:
    """Register a callback handler with an auto-generated UUID-based ID.

    Args:
        handler: Callable to invoke when the callback is executed.

    Returns:
        The auto-generated callback_id.

    """
    return _registry.register_auto(handler)


def execute_callback(callback_id: str) -> bool:
    """Execute the handler for a callback_id.

    Args:
        callback_id: The callback ID to execute.

    Returns:
        True if the callback was found and executed, False otherwise.

    """
    success, _ = _registry.execute(callback_id)
    return success


def unregister_callback(callback_id: str) -> bool:
    """Unregister a callback handler.

    Args:
        callback_id: The callback ID to unregister.

    Returns:
        True if the callback was found and removed, False otherwise.

    """
    return _registry.unregister(callback_id)


def clear_all_callbacks() -> None:
    """Clear all registered callbacks.

    Primarily useful for testing.
    """
    _registry.clear()
