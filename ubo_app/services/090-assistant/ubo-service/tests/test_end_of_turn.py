"""Tests for the end-of-turn phrase detector."""

from __future__ import annotations

import unittest

from ubo_assistant.end_of_turn import match_end_of_turn_phrase


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


if __name__ == '__main__':
    unittest.main()
