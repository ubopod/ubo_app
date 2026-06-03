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

    def test_mid_phrase_period_with_space_matches(self) -> None:
        """A period inserted mid-phrase (after a pause) still matches."""
        match = match_end_of_turn_phrase(
            'i am done. talking',
            ('i am done talking',),
        )
        self.assertEqual(match, 'i am done talking')  # noqa: PT009

    def test_mid_phrase_period_without_space_matches(self) -> None:
        """A period with no surrounding space does not merge the words."""
        match = match_end_of_turn_phrase(
            'i am done.talking',
            ('i am done talking',),
        )
        self.assertEqual(match, 'i am done talking')  # noqa: PT009

    def test_mid_phrase_spaced_period_matches(self) -> None:
        """A space-period-space sequence does not leave a double space."""
        match = match_end_of_turn_phrase(
            'i am done . talking',
            ('i am done talking',),
        )
        self.assertEqual(match, 'i am done talking')  # noqa: PT009

    def test_contraction_phrase_matches_mid_period(self) -> None:
        """A contracted phrase still matches across an inserted period."""
        match = match_end_of_turn_phrase(
            "i'm done. talking",
            ("i'm done talking",),
        )
        self.assertEqual(match, "i'm done talking")  # noqa: PT009

    def test_trailing_word_after_phrase_matches(self) -> None:
        """A short completion after the phrase still ends the turn."""
        self.assertEqual(  # noqa: PT009
            match_end_of_turn_phrase("i'm done talking", ("i'm done",)),
            "i'm done",
        )

    def test_two_trailing_words_after_phrase_match(self) -> None:
        """Up to two trailing words still count as end-of-utterance."""
        self.assertEqual(  # noqa: PT009
            match_end_of_turn_phrase("i'm done talking now", ("i'm done",)),
            "i'm done",
        )

    def test_trailing_words_with_mid_period_match(self) -> None:
        """The 'i am done talking' case from the field reports matches."""
        self.assertEqual(  # noqa: PT009
            match_end_of_turn_phrase('i am done. talking', ('i am done',)),
            'i am done',
        )

    def test_many_trailing_words_do_not_match(self) -> None:
        """More than two trailing words is a continuation, not an end."""
        self.assertIsNone(  # noqa: PT009
            match_end_of_turn_phrase(
                "i'm done thinking what next please",
                ("i'm done",),
            ),
        )

    def test_phrase_in_middle_of_text_does_not_match(self) -> None:
        """A phrase trailed by a full continuation does not trigger a stop."""
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

    async def test_matched_phrase_is_not_forwarded(self) -> None:
        """A matched end-phrase transcript is swallowed, not sent downstream."""
        strategy = MagicMock()
        strategy.trigger_phrase_end_of_turn = AsyncMock()
        detector, _ = _make_detector(
            end_of_turn_phrases=("i'm done",),
            strategy=strategy,
        )

        frame = TranscriptionFrame(
            user_id='u',
            timestamp='2025-01-01T00:00:00Z',
            text="i'm done talking",
        )

        push_frame = AsyncMock()
        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            EndOfTurnPhraseDetector,
            'push_frame',
            new=push_frame,
        ):
            await detector.process_frame(frame, FrameDirection.DOWNSTREAM)

        strategy.trigger_phrase_end_of_turn.assert_awaited_once()
        push_frame.assert_not_awaited()

    async def test_unmatched_frame_is_forwarded(self) -> None:
        """A non-matching transcript is forwarded downstream unchanged."""
        strategy = MagicMock()
        strategy.trigger_phrase_end_of_turn = AsyncMock()
        detector, _ = _make_detector(
            end_of_turn_phrases=("i'm done",),
            strategy=strategy,
        )

        frame = TranscriptionFrame(
            user_id='u',
            timestamp='2025-01-01T00:00:00Z',
            text='what is the weather',
        )

        push_frame = AsyncMock()
        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            EndOfTurnPhraseDetector,
            'push_frame',
            new=push_frame,
        ):
            await detector.process_frame(frame, FrameDirection.DOWNSTREAM)

        push_frame.assert_awaited_once()

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
