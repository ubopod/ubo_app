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

    Supports prefix/wildcard handlers: registering ``"foo:bar:*"`` matches any
    ID that starts with ``"foo:bar:"``.  The handler receives the full
    ``handler_id`` as its first argument so it can parse the variable suffix.
    """

    def __init__(self, name: str) -> None:
        """Initialize the registry.

        Args:
            name: Human-readable name for logging (e.g., 'action', 'callback').

        """
        self._name = name
        self._handlers: dict[str, Callable[..., object]] = {}
        # Prefix handlers: prefix -> handler (registered via "prefix:*")
        self._prefix_handlers: dict[str, Callable[..., object]] = {}

    def register(
        self,
        handler_id: str,
        handler: Callable[..., object],
        *,
        allow_reregister: bool = False,
    ) -> Callable[..., object]:
        """Register a handler for the given ID.

        If *handler_id* ends with ``":*"``, the handler is registered as a
        prefix handler.  It will match any ID that starts with the prefix
        (everything before ``":*"``).  The handler is called with the full
        ``handler_id`` as its first argument.

        Args:
            handler_id: Unique identifier (or ``"prefix:*"`` pattern).
            handler: Callable to invoke when executed.
            allow_reregister: If True, silently replaces an existing handler
                with the same ID. If False (default), raises ValueError.

        Returns:
            The handler function (for chaining/decorator use).

        Raises:
            ValueError: If handler_id is already registered and
                allow_reregister is False.

        """
        if handler_id.endswith(':*'):
            prefix = handler_id[:-1]  # keep trailing ":" for matching
            if prefix in self._prefix_handlers and not allow_reregister:
                msg = (
                    f"{self._name.capitalize()} prefix '{handler_id}' "
                    f'is already registered'
                )
                raise ValueError(msg)
            self._prefix_handlers[prefix] = handler
            logger.debug(
                'Registered %s prefix handler: %s', self._name, handler_id,
            )
            return handler

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
            handler_id: The handler ID (or ``"prefix:*"`` pattern) to unregister.

        Returns:
            True if the handler was found and removed, False otherwise.

        """
        if handler_id.endswith(':*'):
            prefix = handler_id[:-1]
            if prefix in self._prefix_handlers:
                del self._prefix_handlers[prefix]
                logger.debug(
                    'Unregistered %s prefix handler: %s',
                    self._name,
                    handler_id,
                )
                return True
            return False
        if handler_id in self._handlers:
            del self._handlers[handler_id]
            logger.debug('Unregistered %s handler: %s', self._name, handler_id)
            return True
        return False

    def _find_prefix_handler(
        self,
        handler_id: str,
    ) -> Callable[..., object] | None:
        """Find a prefix handler matching *handler_id*.

        Tries each registered prefix; the longest match wins.
        """
        best: Callable[..., object] | None = None
        best_len = 0
        for prefix, handler in self._prefix_handlers.items():
            if handler_id.startswith(prefix) and len(prefix) > best_len:
                best = handler
                best_len = len(prefix)
        return best

    def get(self, handler_id: str) -> Callable[..., object] | None:
        """Get the handler for an ID without executing it.

        Falls back to prefix handlers if no exact match is found.

        Args:
            handler_id: The handler ID to look up.

        Returns:
            The handler callable, or None if not found.

        """
        handler = self._handlers.get(handler_id)
        if handler is not None:
            return handler
        return self._find_prefix_handler(handler_id)

    def execute(self, handler_id: str) -> tuple[bool, object]:
        """Execute the handler for an ID.

        Exact-match handlers are called with no arguments.  Prefix handlers
        are called with the full *handler_id* so they can parse the suffix.

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

        # Try prefix handlers
        prefix_handler = self._find_prefix_handler(handler_id)
        if prefix_handler is not None:
            logger.debug('Executing %s (prefix): %s', self._name, handler_id)
            try:
                return True, prefix_handler(handler_id)
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
        self._prefix_handlers.clear()
        logger.debug('Cleared all %s handlers', self._name)

    def __contains__(self, handler_id: str) -> bool:
        """Check if a handler ID is registered."""
        if handler_id in self._handlers:
            return True
        return self._find_prefix_handler(handler_id) is not None
