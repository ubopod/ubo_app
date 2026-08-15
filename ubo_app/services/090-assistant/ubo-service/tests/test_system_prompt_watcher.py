"""Tests for how the system-prompt watcher composes the LLM system message."""

from __future__ import annotations

import unittest
from typing import Any, cast

from betterproto.lib.google.protobuf import BoolValue, StringValue

from ubo_assistant.constants import DEFAULT_SYSTEM_MESSAGE, DEFAULT_TOOLS_MESSAGE
from ubo_assistant.system_prompt_watcher import SystemPromptWatcher


def _payload(custom: str, *, is_default_enabled: bool) -> list[Any]:
    """Build an autorun payload in the shape the gRPC client delivers.

    Scalar selectors arrive as protobuf wrappers, not bare Python values.
    Passing raw ``str``/``bool`` here would let a missing ``.value`` unwrap
    pass unnoticed — which is exactly how one shipped.
    """
    return [StringValue(value=custom), BoolValue(value=is_default_enabled)]


class FakeClient:
    """Stands in for ``UboRPCClient``; captures the autorun callback."""

    def __init__(self) -> None:
        """Start with no registered callback."""
        self.callback: Any = None
        self.selectors: list[str] = []

    def autorun(self, selectors: list[str]) -> Any:  # noqa: ANN401
        """Record the selectors and capture the decorated handler."""
        self.selectors = selectors

        def decorator(function: Any) -> Any:  # noqa: ANN401
            self.callback = function
            return function

        return decorator


def _make_watcher() -> tuple[SystemPromptWatcher, FakeClient]:
    client = FakeClient()
    watcher = SystemPromptWatcher(cast('Any', client))
    return watcher, client


class SystemPromptCompositionTests(unittest.TestCase):
    """``compose`` assembles the built-in and user prompts."""

    def test_subscribes_to_both_slices(self) -> None:
        """Both the composed text and the default flag are watched."""
        _watcher, client = _make_watcher()

        self.assertEqual(  # noqa: PT009
            client.selectors,
            [
                'state.assistant.active_system_prompt',
                'state.assistant.is_default_system_prompt_enabled',
            ],
        )

    def test_defaults_to_the_builtin_prompt(self) -> None:
        """Before any state arrives, behavior matches the pre-feature default."""
        watcher, _client = _make_watcher()

        self.assertEqual(  # noqa: PT009
            watcher.compose(include_tools=False),
            DEFAULT_SYSTEM_MESSAGE,
        )

    def test_tools_message_appended_only_when_requested(self) -> None:
        """Providers without tool support get the prompt without tool rules."""
        watcher, _client = _make_watcher()

        self.assertEqual(  # noqa: PT009
            watcher.compose(include_tools=True),
            f'{DEFAULT_SYSTEM_MESSAGE}\n\n{DEFAULT_TOOLS_MESSAGE}',
        )

    def test_custom_prompt_follows_the_builtin(self) -> None:
        """With both enabled, the built-in comes first."""
        watcher, client = _make_watcher()

        client.callback(_payload('Answer like a pirate.', is_default_enabled=True))

        self.assertEqual(  # noqa: PT009
            watcher.compose(include_tools=False),
            f'{DEFAULT_SYSTEM_MESSAGE}\n\nAnswer like a pirate.',
        )

    def test_disabled_default_leaves_only_the_custom_prompt(self) -> None:
        """Turning the built-in off drops it from the composed message."""
        watcher, client = _make_watcher()

        client.callback(_payload('Answer like a pirate.', is_default_enabled=False))

        self.assertEqual(  # noqa: PT009
            watcher.compose(include_tools=False),
            'Answer like a pirate.',
        )

    def test_everything_disabled_falls_back_to_the_builtin(self) -> None:
        """An empty system message is never sent."""
        watcher, client = _make_watcher()

        client.callback(_payload('', is_default_enabled=False))

        self.assertEqual(  # noqa: PT009
            watcher.compose(include_tools=False),
            DEFAULT_SYSTEM_MESSAGE,
        )

    def test_subscribers_notified_only_on_change(self) -> None:
        """Repeating the same values doesn't re-push the system message."""
        watcher, client = _make_watcher()
        calls = []
        watcher.subscribe(lambda: calls.append(None))

        client.callback(_payload('Be terse.', is_default_enabled=True))
        client.callback(_payload('Be terse.', is_default_enabled=True))

        self.assertEqual(len(calls), 1)  # noqa: PT009

        client.callback(_payload('Be terse.', is_default_enabled=False))

        self.assertEqual(len(calls), 2)  # noqa: PT009

    def test_unsubscribe_stops_notifications(self) -> None:
        """The returned callable detaches the subscriber."""
        watcher, client = _make_watcher()
        calls = []
        unsubscribe = watcher.subscribe(lambda: calls.append(None))

        unsubscribe()
        client.callback(_payload('Be terse.', is_default_enabled=True))

        self.assertEqual(calls, [])  # noqa: PT009
