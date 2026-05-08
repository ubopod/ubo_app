"""Tests for the assistant policy watcher's message-to-context mapping."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import ClassVar

from ubo_assistant.policy_watcher import (
    PolicyContext,
    _policy_message_to_context,
)


@dataclass
class FakePhrasesMessage:
    """Stand-in for ``AssistantTriggerPolicyEndOfTurnPhrases``."""

    items: ClassVar[list[str]] = []


class PolicyMessageMappingTests(unittest.TestCase):
    """Map a betterproto policy message into a :class:`PolicyContext`."""

    def test_none_message_yields_empty_context(self) -> None:
        """No active policy → inert context."""
        self.assertEqual(  # noqa: PT009
            _policy_message_to_context(None),
            PolicyContext.empty(),
        )

    def test_silence_timeout_only(self) -> None:
        """Silence-timeout-only policies populate that field."""
        @dataclass
        class FakePolicyMessage:
            silence_timeout_seconds: float | None = 2.0
            requires_phrase_for_stop: bool = False
            end_of_turn_phrases: object = None

        context = _policy_message_to_context(FakePolicyMessage())

        self.assertEqual(context.silence_timeout_seconds, 2.0)  # noqa: PT009
        self.assertEqual(context.end_of_turn_phrases, ())  # noqa: PT009
        self.assertFalse(context.requires_phrase_for_stop)  # noqa: PT009

    def test_end_of_turn_phrases_populate_tuple(self) -> None:
        """End-of-turn phrase wrapper unwraps into a tuple."""
        @dataclass
        class FakePhrases:
            items: list[str]

        @dataclass
        class FakePolicyMessage:
            silence_timeout_seconds: float | None
            requires_phrase_for_stop: bool
            end_of_turn_phrases: FakePhrases | None

        msg = FakePolicyMessage(
            silence_timeout_seconds=None,
            requires_phrase_for_stop=True,
            end_of_turn_phrases=FakePhrases(items=["i'm done", 'thanks bye']),
        )

        context = _policy_message_to_context(msg)

        self.assertIsNone(context.silence_timeout_seconds)  # noqa: PT009
        self.assertEqual(  # noqa: PT009
            context.end_of_turn_phrases,
            ("i'm done", 'thanks bye'),
        )
        self.assertTrue(context.requires_phrase_for_stop)  # noqa: PT009


if __name__ == '__main__':
    unittest.main()
