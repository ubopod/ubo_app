"""Generic handler registry for mapping string IDs to callable handlers.

This module provides a reusable `HandlerRegistry` class that eliminates
duplicated code between the action registry and callback registry.
Both registries share the same core pattern: register/unregister/execute
handlers by string ID.

Usage:
    action_registry = HandlerRegistry('action')
    callback_registry = HandlerRegistry('callback')
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from ubo_app.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable


class HandlerRegistry:
    """A generic registry mapping string IDs to callable handlers.

    Provides register, unregister, execute, get, list, and clear operations
    with consistent logging and error handling.
    """

    def __init__(self, name: str) -> None:
        """Initialize the registry.

        Args:
            name: Human-readable name for logging (e.g., 'action', 'callback').

        """
        self._name = name
        self._handlers: dict[str, Callable[[], object]] = {}

    def register(
        self,
        handler_id: str,
        handler: Callable[[], object],
        *,
        allow_reregister: bool = False,
    ) -> Callable[[], object]:
        """Register a handler for the given ID.

        Args:
            handler_id: Unique identifier for the handler.
            handler: Callable to invoke when executed.
            allow_reregister: If True, silently replaces an existing handler
                with the same ID. If False (default), raises ValueError.

        Returns:
            The handler function (for chaining/decorator use).

        Raises:
            ValueError: If handler_id is already registered and
                allow_reregister is False.

        """
        if handler_id in self._handlers and not allow_reregister:
            msg = f"{self._name.capitalize()} '{handler_id}' is already registered"
            raise ValueError(msg)
        self._handlers[handler_id] = handler
        logger.debug('Registered %s handler: %s', self._name, handler_id)
        return handler

    def register_auto(self, handler: Callable[[], object]) -> str:
        """Register a handler with an auto-generated UUID-based ID.

        Args:
            handler: Callable to invoke when executed.

        Returns:
            The auto-generated handler ID.

        """
        handler_id = f'{self._name}:{uuid4().hex}'
        self._handlers[handler_id] = handler
        logger.debug('Registered auto %s handler: %s', self._name, handler_id)
        return handler_id

    def unregister(self, handler_id: str) -> bool:
        """Unregister a handler.

        Args:
            handler_id: The handler ID to unregister.

        Returns:
            True if the handler was found and removed, False otherwise.

        """
        if handler_id in self._handlers:
            del self._handlers[handler_id]
            logger.debug('Unregistered %s handler: %s', self._name, handler_id)
            return True
        return False

    def get(self, handler_id: str) -> Callable[[], object] | None:
        """Get the handler for an ID without executing it.

        Args:
            handler_id: The handler ID to look up.

        Returns:
            The handler callable, or None if not found.

        """
        return self._handlers.get(handler_id)

    def execute(self, handler_id: str) -> tuple[bool, object]:
        """Execute the handler for an ID.

        Args:
            handler_id: The handler ID to execute.

        Returns:
            A ``(success, result)`` tuple.  ``success`` is True when the
            handler was found and ran without raising.  ``result`` is the
            handler's return value on success, or None otherwise.

        """
        handler = self._handlers.get(handler_id)
        if handler is not None:
            logger.debug('Executing %s: %s', self._name, handler_id)
            try:
                return True, handler()
            except Exception:
                logger.exception('Error executing %s: %s', self._name, handler_id)
                return False, None
        logger.warning('No handler registered for %s: %s', self._name, handler_id)
        return False, None

    def get_registered_ids(self) -> list[str]:
        """Get list of all registered handler IDs.

        Returns:
            List of registered handler ID strings.

        """
        return list(self._handlers.keys())

    def clear(self) -> None:
        """Clear all registered handlers.

        Primarily useful for testing.
        """
        self._handlers.clear()
        logger.debug('Cleared all %s handlers', self._name)

    def __contains__(self, handler_id: str) -> bool:
        """Check if a handler ID is registered."""
        return handler_id in self._handlers
