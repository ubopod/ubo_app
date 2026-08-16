"""Subscribes to the user's system-prompt selection and composes it.

The core keeps the user's prompts in ``state.assistant.system_prompts`` and
joins the enabled ones into the ``active_system_prompt`` scalar (a gRPC
selector can't return a container). The built-in ``DEFAULT_SYSTEM_MESSAGE``
lives here rather than in the store — the core can't import this package — so
only a flag crosses the boundary and this module reassembles the full message.

One subscription serves both consumers: the live pipeline's LLM switcher and
the one-shot request handler.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from loguru import logger

from ubo_assistant.constants import DEFAULT_SYSTEM_MESSAGE, DEFAULT_TOOLS_MESSAGE

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_bindings.client import UboRPCClient


class SystemPromptWatcher:
    """Single autorun subscription over the user's system-prompt selection."""

    def __init__(self, client: UboRPCClient) -> None:
        """Start subscribing to the composed prompt and the default flag."""
        self._client = client
        self._custom = ''
        self._is_default_enabled = True
        self._subscribers: list[Callable[[], None]] = []

        @client.autorun([
            'state.assistant.active_system_prompt',
            'state.assistant.is_default_system_prompt_enabled',
        ])
        def _handle(data: list) -> None:
            self._update_from_autorun_data(data)

        # Keep a reference so the closure isn't garbage-collected.
        self._autorun_handle = _handle

    def compose(self, *, include_tools: bool) -> str:
        """Build the system message to send to the LLM.

        ``include_tools`` appends the tool-usage instructions; providers that
        don't support tools get the prompt without them.
        """
        parts = [DEFAULT_SYSTEM_MESSAGE] if self._is_default_enabled else []
        if self._custom.strip():
            parts.append(self._custom.strip())
        if not parts:
            # The user disabled the default and enabled nothing else. An empty
            # system message makes some providers behave erratically, so fall
            # back rather than send nothing.
            parts = [DEFAULT_SYSTEM_MESSAGE]
        if include_tools:
            parts.append(DEFAULT_TOOLS_MESSAGE)
        return '\n\n'.join(parts)

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register *callback* to be invoked on every prompt change.

        Unlike :class:`PolicyWatcher`, the callback takes no argument — the
        composed text depends on the caller's ``include_tools``, so subscribers
        re-read it via :meth:`compose`. Returns an unsubscribe callable.
        """
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._subscribers.remove(callback)

        return _unsubscribe

    def _update_from_autorun_data(self, data: list) -> None:
        # Scalars cross the wire as protobuf wrappers — ``StringValue`` /
        # ``BoolValue``, never bare ``str`` / ``bool`` — so the payload is in
        # ``.value``. Same unwrap the switcher's ``selected_llm`` autorun does.
        # ``None`` only appears if the server encoded an unset value.
        custom_message = data[0] if len(data) > 0 else None
        default_message = data[1] if len(data) > 1 else None
        custom = custom_message.value if custom_message is not None else ''
        is_default_enabled = (
            default_message.value if default_message is not None else True
        )
        if (custom, is_default_enabled) == (self._custom, self._is_default_enabled):
            return
        logger.info(
            'System prompt selection updated {extra}',
            extra={
                'custom_length': len(custom),
                'is_default_enabled': is_default_enabled,
            },
        )
        self._custom = custom
        self._is_default_enabled = is_default_enabled
        for subscriber in list(self._subscribers):
            try:
                subscriber()
            except Exception:  # pragma: no cover - defensive
                logger.exception('SystemPromptWatcher subscriber raised')
