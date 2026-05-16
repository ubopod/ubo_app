"""Tests for the end-of-turn phrase detector."""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from ubo_assistant.end_of_turn import (
    EndOfTurnPhraseDetector,
    match_end_of_turn_phrase,
)
from ubo_assistant.policy_watcher import PolicyContext, PolicyWatcher


class MatchEndOfTurnPhraseTests(unittest.TestCase):
    """Pure-function tests for ``match_end_of_turn_phrase``."""

    def test_no_phrases_returns_none(self) -> None:
        """Empty policy phrases never match."""
        self.assertIsNone(match_end_of_turn_phrase("i'm done", ()))  # noqa: PT009

    def test_empty_text_returns_none(self) -> None:
        """Empty user transcript never matches."""
        self.assertIsNone(  # noqa: PT009
            match_end_of_turn_phrase('', ("i'm done",)),
        )

    def test_endswith_phrase_matches(self) -> None:
        """Transcript ending in the policy phrase matches."""
        match = match_end_of_turn_phrase(
            "okay i'm done",
            ("i'm done", "that's it"),
        )
        self.assertEqual(match, "i'm done")  # noqa: PT009

    def test_match_is_case_insensitive(self) -> None:
        """Matching ignores casing differences."""
        match = match_end_of_turn_phrase(
            "Okay I'M DONE",
            ("i'm done",),
        )
        self.assertEqual(match, "i'm done")  # noqa: PT009

    def test_punctuation_is_stripped_from_text(self) -> None:
        """Trailing punctuation in the transcript does not block a match."""
        match = match_end_of_turn_phrase(
            "okay i'm done.",
            ("i'm done",),
        )
        self.assertEqual(match, "i'm done")  # noqa: PT009

    def test_punctuation_is_stripped_from_phrase(self) -> None:
        """Punctuation in the policy phrase is normalised away too."""
        match = match_end_of_turn_phrase(
            'thats all',
            ("that's all",),
        )
        self.assertEqual(match, "that's all")  # noqa: PT009

    def test_phrase_in_middle_of_text_does_not_match(self) -> None:
        """Only end-of-utterance triggers a stop."""
        self.assertIsNone(  # noqa: PT009
            match_end_of_turn_phrase(
                "i'm done thinking, what next",
                ("i'm done",),
            ),
        )

    def test_first_match_wins(self) -> None:
        """Returns the policy phrase that matched first in priority order."""
        match = match_end_of_turn_phrase(
            'thanks bye',
            ("that's all", 'thanks bye'),
        )
        self.assertEqual(match, 'thanks bye')  # noqa: PT009


class _FakePolicyWatcher:
    """Stand-in exposing the ``context`` attribute the detector reads."""

    def __init__(self, context: PolicyContext) -> None:
        """Store *context* used as the live policy snapshot."""
        self.context = context


def _make_detector(
    *,
    end_of_turn_phrases: tuple[str, ...],
    strategy: Any,  # noqa: ANN401
) -> tuple[EndOfTurnPhraseDetector, MagicMock]:
    client = MagicMock()
    watcher = _FakePolicyWatcher(
        PolicyContext(end_of_turn_phrases=end_of_turn_phrases),
    )
    detector = EndOfTurnPhraseDetector(
        client=client,
        policy_watcher=cast('PolicyWatcher', watcher),
        user_turn_stop_strategy=strategy,
    )
    return detector, client


class EndOfTurnPhraseDetectorTests(unittest.IsolatedAsyncioTestCase):
    """Behavioural tests for the detector → strategy / dispatch wiring."""

    async def test_phrase_match_triggers_strategy_and_dispatches_stop(
        self,
    ) -> None:
        """Matching phrase fires the strategy then dispatches the stop action."""
        strategy = MagicMock()
        strategy.trigger_phrase_end_of_turn = AsyncMock()
        detector, client = _make_detector(
            end_of_turn_phrases=("i'm done",),
            strategy=strategy,
        )

        frame = TranscriptionFrame(
            user_id='u',
            timestamp='2025-01-01T00:00:00Z',
            text="okay i'm done",
        )

        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            EndOfTurnPhraseDetector,
            'push_frame',
            new=AsyncMock(),
        ):
            await detector.process_frame(frame, FrameDirection.DOWNSTREAM)

        strategy.trigger_phrase_end_of_turn.assert_awaited_once()
        self.assertEqual(client.dispatch.call_count, 1)  # noqa: PT009

    async def test_no_phrase_does_not_trigger_strategy(self) -> None:
        """No matching phrase → strategy not called, no dispatch."""
        strategy = MagicMock()
        strategy.trigger_phrase_end_of_turn = AsyncMock()
        detector, client = _make_detector(
            end_of_turn_phrases=("i'm done",),
            strategy=strategy,
        )

        frame = TranscriptionFrame(
            user_id='u',
            timestamp='2025-01-01T00:00:00Z',
            text='hello there',
        )

        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            EndOfTurnPhraseDetector,
            'push_frame',
            new=AsyncMock(),
        ):
            await detector.process_frame(frame, FrameDirection.DOWNSTREAM)

        strategy.trigger_phrase_end_of_turn.assert_not_awaited()
        self.assertEqual(client.dispatch.call_count, 0)  # noqa: PT009

    async def test_empty_phrases_keeps_detector_inert(self) -> None:
        """Policy with no end phrases never triggers strategy or dispatch."""
        strategy = MagicMock()
        strategy.trigger_phrase_end_of_turn = AsyncMock()
        detector, client = _make_detector(
            end_of_turn_phrases=(),
            strategy=strategy,
        )

        frame = TranscriptionFrame(
            user_id='u',
            timestamp='2025-01-01T00:00:00Z',
            text="i'm done",
        )

        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            EndOfTurnPhraseDetector,
            'push_frame',
            new=AsyncMock(),
        ):
            await detector.process_frame(frame, FrameDirection.DOWNSTREAM)

        strategy.trigger_phrase_end_of_turn.assert_not_awaited()
        self.assertEqual(client.dispatch.call_count, 0)  # noqa: PT009


if __name__ == '__main__':
    unittest.main()
