"""Compact utterance-pattern expansion for voice commands.

A single pattern stands in for many concrete utterances and is expanded to the
full set of phrases it describes (the speech engine is fed an explicit phrase
list, so expansion happens up front rather than via runtime regex matching):

    [a, b, c]   required choice  -> say exactly one of a/b/c
    (x)         optional         -> say it or omit it
    (a, b)      optional choice  -> omit, or say one of a/b
    plain text  literal phrase

Groups nest freely. ``,`` separates alternatives (``|`` is accepted as an
alias). ``(?x)`` is accepted and treated the same as ``(x)``. A backslash
escapes a special character. Plain text with no group characters expands to
itself, so existing simple utterances keep working unchanged.
"""

from __future__ import annotations

from functools import lru_cache

DEFAULT_LIMIT = 500


class PatternError(ValueError):
    """Raised for a malformed pattern or an expansion exceeding the cap."""


def _normalize(text: str) -> str:
    """Collapse internal whitespace runs and trim ends.

    Keeps a dropped mid-sentence optional from leaving a double space.
    """
    return ' '.join(text.split())


class _Parser:
    """Recursive-descent parser that expands a pattern to a list of phrases.

    Grammar::

        sequence := token*
        token    := literal | '[' alternatives ']' | '(' alternatives ')'
        alternatives := sequence (separator sequence)*

    ``[...]`` is a required choice; ``(...)`` is optional (an extra empty branch
    is added). Each parse step returns the list of all expansions of the
    fragment; sequences combine by concatenation (literal runs carry their own
    spacing, normalized at the end).
    """

    _SEPARATORS = frozenset({',', '|'})

    def __init__(self, text: str, limit: int) -> None:
        self.text = text
        self.pos = 0
        self.limit = limit

    def _peek(self) -> str | None:
        return self.text[self.pos] if self.pos < len(self.text) else None

    def parse(self) -> list[str]:
        result = self._parse_sequence(stop=frozenset())
        if self.pos != len(self.text):
            msg = f'Unbalanced {self.text[self.pos]!r} at position {self.pos}'
            raise PatternError(msg)
        return result

    def _parse_sequence(self, stop: frozenset[str]) -> list[str]:
        segments: list[list[str]] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                segments.append([''.join(buffer)])
                buffer.clear()

        while True:
            char = self._peek()
            if char is None or char in stop:
                break
            if char == '\\':
                self.pos += 1
                escaped = self._peek()
                if escaped is None:
                    msg = 'Dangling escape character'
                    raise PatternError(msg)
                buffer.append(escaped)
                self.pos += 1
            elif char == '[':
                flush()
                self.pos += 1
                segments.append(self._parse_alternatives(']'))
            elif char == '(':
                flush()
                self.pos += 1
                segments.append([*self._parse_alternatives(')'), ''])
            elif char in (']', ')'):
                msg = f'Unbalanced {char!r} at position {self.pos}'
                raise PatternError(msg)
            else:
                buffer.append(char)
                self.pos += 1
        flush()
        return self._combine(segments)

    def _parse_alternatives(self, close: str) -> list[str]:
        # Opening bracket already consumed. '(?x)' sugar: a leading '?' inside an
        # optional group is ignored.
        if close == ')' and self._peek() == '?':
            self.pos += 1
        alternatives: list[str] = []
        while True:
            alternatives.extend(
                self._parse_sequence(stop=self._SEPARATORS | {close}),
            )
            char = self._peek()
            if char is None:
                msg = f'Missing closing {close!r}'
                raise PatternError(msg)
            self.pos += 1
            if char == close:
                return alternatives
            # otherwise it was a separator; continue with the next alternative

    def _combine(self, segments: list[list[str]]) -> list[str]:
        results = ['']
        for segment in segments:
            results = [prefix + option for prefix in results for option in segment]
            if len(results) > self.limit:
                msg = f'Pattern expands to more than {self.limit} phrases'
                raise PatternError(msg)
        return results


@lru_cache(maxsize=512)
def _expand_cached(pattern: str, limit: int) -> tuple[str, ...]:
    raw = _Parser(pattern, limit).parse()
    deduped = list(dict.fromkeys(_normalize(phrase) for phrase in raw))
    concrete = [phrase for phrase in deduped if phrase]
    if not concrete:
        msg = 'Pattern produced no concrete phrase'
        raise PatternError(msg)
    if len(concrete) > limit:
        msg = f'Pattern expands to more than {limit} phrases'
        raise PatternError(msg)
    return tuple(concrete)


def expand_pattern(pattern: str, *, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Expand *pattern* to its list of concrete phrases (order-preserving, deduped).

    A plain phrase (no group characters) returns ``[phrase]``.

    Raises:
        PatternError: if the pattern is malformed or expands beyond *limit*.

    """
    return list(_expand_cached(pattern.strip(), limit))
