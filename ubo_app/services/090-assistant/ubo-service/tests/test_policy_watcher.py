"""Tests for the assistant policy watcher's message-to-context mapping."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from types import SimpleNamespace

from ubo_assistant.policy_watcher import (
    PolicyContext,
    _policy_message_to_context,
)

# betterproto delivers ``completion_mode`` as an enum whose ``.name`` is the
# proto member name. Stand in for it with a namespace exposing ``.name``.
_SILENCE_MODE = SimpleNamespace(name='SILENCE')
_MANUAL_MODE = SimpleNamespace(name='MANUAL')


class PolicyMessageMappingTests(unittest.TestCase):
    """Map a betterproto policy message into a :class:`PolicyContext`."""

    def test_none_message_yields_empty_context(self) -> None:
        """No active policy → inert context."""
        self.assertEqual(  # noqa: PT009
            _policy_message_to_context(None),
            PolicyContext.empty(),
        )

    def test_silence_timeout_only(self) -> None:
        """Silence-timeout-only policies populate that field, mode silence."""
        @dataclass
        class FakePolicyMessage:
            silence_timeout_seconds: float | None
            completion_mode: object
            end_of_turn_phrases: object

        context = _policy_message_to_context(
            FakePolicyMessage(2.0, _SILENCE_MODE, None),
        )

        self.assertEqual(context.silence_timeout_seconds, 2.0)  # noqa: PT009
        self.assertEqual(context.end_of_turn_phrases, ())  # noqa: PT009
        self.assertEqual(context.completion_mode, 'silence')  # noqa: PT009
        self.assertFalse(context.is_manual)  # noqa: PT009

    def test_manual_mode_maps_to_is_manual(self) -> None:
        """A MANUAL completion mode resolves to a manual context."""
        @dataclass
        class FakePolicyMessage:
            silence_timeout_seconds: float | None
            completion_mode: object
            end_of_turn_phrases: object

        context = _policy_message_to_context(
            FakePolicyMessage(None, _MANUAL_MODE, None),
        )

        self.assertEqual(context.completion_mode, 'manual')  # noqa: PT009
        self.assertTrue(context.is_manual)  # noqa: PT009

    def test_real_betterproto_manual_policy_round_trips(self) -> None:
        """A real wire-serialized MANUAL policy maps to a manual context.

        Guards the exact autorun payload the strategy receives — a
        ``FromString``-decoded ``AssistantTriggerPolicy``, not a fake.
        """
        from ubo_bindings.ubo.v1 import (
            AssistantTriggerPolicy,
            AssistantTurnCompletionMode,
        )

        msg = AssistantTriggerPolicy.FromString(
            bytes(
                AssistantTriggerPolicy(
                    completion_mode=AssistantTurnCompletionMode.MANUAL,
                ),
            ),
        )

        context = _policy_message_to_context(msg)

        self.assertEqual(context.completion_mode, 'manual')  # noqa: PT009
        self.assertTrue(context.is_manual)  # noqa: PT009

    def test_end_of_turn_phrases_populate_tuple(self) -> None:
        """End-of-turn phrase wrapper unwraps into a tuple."""
        @dataclass
        class FakePhrases:
            items: list[str]

        @dataclass
        class FakePolicyMessage:
            silence_timeout_seconds: float | None
            completion_mode: object
            end_of_turn_phrases: FakePhrases | None

        msg = FakePolicyMessage(
            silence_timeout_seconds=5.0,
            completion_mode=_SILENCE_MODE,
            end_of_turn_phrases=FakePhrases(items=["i'm done", 'thanks bye']),
        )

        context = _policy_message_to_context(msg)

        self.assertEqual(context.silence_timeout_seconds, 5.0)  # noqa: PT009
        self.assertEqual(  # noqa: PT009
            context.end_of_turn_phrases,
            ("i'm done", 'thanks bye'),
        )
        self.assertFalse(context.is_manual)  # noqa: PT009


if __name__ == '__main__':
    unittest.main()
