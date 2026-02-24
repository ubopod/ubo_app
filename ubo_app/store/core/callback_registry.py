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
from uuid import uuid4

from ubo_app.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable

# Global registry mapping callback_id -> handler function
_callback_handlers: dict[str, Callable[[], object]] = {}


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
    if callback_id in _callback_handlers:
        msg = f"Callback '{callback_id}' is already registered"
        raise ValueError(msg)
    _callback_handlers[callback_id] = handler
    logger.debug('Registered callback handler: %s', callback_id)
    return callback_id


def register_auto_callback(handler: Callable[[], object]) -> str:
    """Register a callback handler with an auto-generated UUID-based ID.

    Args:
        handler: Callable to invoke when the callback is executed.

    Returns:
        The auto-generated callback_id.

    """
    callback_id = f'callback:{uuid4().hex}'
    _callback_handlers[callback_id] = handler
    logger.debug('Registered auto callback handler: %s', callback_id)
    return callback_id


def execute_callback(callback_id: str) -> bool:
    """Execute the handler for a callback_id.

    Args:
        callback_id: The callback ID to execute.

    Returns:
        True if the callback was found and executed, False otherwise.

    """
    handler = _callback_handlers.get(callback_id)
    if handler is not None:
        logger.debug('Executing callback: %s', callback_id)
        try:
            handler()
        except Exception:
            logger.exception('Error executing callback: %s', callback_id)
            return False
        return True
    logger.warning('No handler registered for callback: %s', callback_id)
    return False


def unregister_callback(callback_id: str) -> bool:
    """Unregister a callback handler.

    Args:
        callback_id: The callback ID to unregister.

    Returns:
        True if the callback was found and removed, False otherwise.

    """
    if callback_id in _callback_handlers:
        del _callback_handlers[callback_id]
        logger.debug('Unregistered callback handler: %s', callback_id)
        return True
    return False


def clear_all_callbacks() -> None:
    """Clear all registered callbacks.

    Primarily useful for testing.
    """
    _callback_handlers.clear()
    logger.debug('Cleared all callback handlers')
