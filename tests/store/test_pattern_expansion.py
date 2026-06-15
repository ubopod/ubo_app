"""Unit tests for the compact utterance-pattern expander.

The expander is a self-contained pure module in the hyphenated service dir, so
it is loaded by file path. No store/engine involved.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

_PATTERN_PATH = (
    Path(__file__).resolve().parents[2]
    / 'ubo_app'
    / 'services'
    / '090-speech-recognition'
    / 'pattern.py'
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        'sr_pattern_under_test',
        _PATTERN_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pattern = _load()
expand_pattern = pattern.expand_pattern
PatternError = pattern.PatternError


class TestLiterals:
    """Plain phrases pass through unchanged (backward compatible)."""

    def test_plain_phrase_returns_itself(self) -> None:
        """A phrase with no group characters expands to just itself."""
        assert expand_pattern('turn on lights') == ['turn on lights']

    def test_whitespace_is_normalized(self) -> None:
        """Internal whitespace runs collapse and ends are trimmed."""
        assert expand_pattern('  turn   on  lights ') == ['turn on lights']


class TestChoice:
    """``[a, b]`` is a required choice."""

    def test_required_choice(self) -> None:
        """Each alternative becomes its own phrase."""
        assert expand_pattern('[make, brew] coffee') == [
            'make coffee',
            'brew coffee',
        ]

    def test_pipe_separator_alias(self) -> None:
        """``|`` works as an alternative separator alias for ``,``."""
        assert expand_pattern('[a | b] c') == ['a c', 'b c']


class TestOptional:
    """``(x)`` is optional (present or omitted)."""

    def test_optional_word(self) -> None:
        """An optional word yields both the present and omitted forms."""
        assert expand_pattern('(please) help') == ['please help', 'help']

    def test_optional_in_middle_has_no_double_space(self) -> None:
        """Omitting a mid-sentence optional does not leave a double space."""
        assert expand_pattern('turn (it) off') == ['turn it off', 'turn off']

    def test_optional_choice(self) -> None:
        """An optional choice omits, or picks one alternative."""
        assert expand_pattern('go (back, home)') == ['go back', 'go home', 'go']

    def test_question_mark_alias(self) -> None:
        """``(?x)`` is accepted and means the same as ``(x)``."""
        assert expand_pattern('(?the) light') == ['the light', 'light']


class TestNestingAndProduct:
    """Sequences and nested groups expand combinatorially."""

    def test_the_48_phrase_example(self) -> None:
        """The documented example expands to 48 unique phrases."""
        result = expand_pattern(
            '[create, set up] [wifi, wireless] (connection) '
            '[via, using] [web, web ui, web dashboard]',
        )
        assert len(result) == 48
        assert 'create wifi connection via web' in result
        assert 'set up wireless using web dashboard' in result
        # optional 'connection' omitted variant
        assert 'create wifi via web' in result

    def test_nested_group_inside_choice(self) -> None:
        """A group nested inside an alternative expands correctly."""
        assert expand_pattern('[turn (it) off, stop]') == [
            'turn it off',
            'turn off',
            'stop',
        ]


class TestDedupeAndEscaping:
    """Duplicate expansions are removed; specials can be escaped."""

    def test_duplicates_removed_preserving_order(self) -> None:
        """Repeated expansions collapse to one, keeping first-seen order."""
        assert expand_pattern('[a, a, b] x') == ['a x', 'b x']

    def test_escaped_specials_are_literal(self) -> None:
        """A backslash escapes a special character to a literal."""
        assert expand_pattern(r'price is \[5\]') == ['price is [5]']


class TestErrors:
    """Malformed patterns and over-cap expansions raise PatternError."""

    def test_missing_closing_bracket(self) -> None:
        """An unterminated group is rejected."""
        with pytest.raises(PatternError):
            expand_pattern('[a, b')

    def test_unbalanced_closing_bracket(self) -> None:
        """A stray closing bracket is rejected."""
        with pytest.raises(PatternError):
            expand_pattern('a]')

    def test_all_optional_has_no_concrete_phrase(self) -> None:
        """A pattern with no concrete phrase is rejected."""
        with pytest.raises(PatternError):
            expand_pattern('()')

    def test_expansion_cap_enforced(self) -> None:
        """An expansion beyond the cap is rejected."""
        with pytest.raises(PatternError):
            expand_pattern('[a, b] [c, d] [e, f]', limit=4)
