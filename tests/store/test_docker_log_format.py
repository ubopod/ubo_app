"""Tests for the Docker log tail's text shaping.

The byte ceiling here is what stops a log tail from reaching an MCU client that
cannot hold it, so it is asserted directly rather than only observed on a pod.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


def _log_format_module() -> ModuleType:
    """Import the log formatter the way the service loader does.

    Read back off the returned module rather than imported at file scope:
    integration/flows tests earlier in the full suite churn ``sys.modules``, and
    a top-level import would leave this test holding a stale generation.
    """
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)
    try:
        return import_module('log_format')
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


def test_keeps_only_the_last_lines() -> None:
    """Only the newest lines survive — a log's value is at its tail."""
    module = _log_format_module()

    raw = '\n'.join(f'line {index}' for index in range(200))
    result = module.format_logs(raw)

    lines = result.splitlines()
    assert len(lines) == module.LOG_TAIL_LINES
    assert lines[-1] == 'line 199'
    assert 'line 0' not in lines


def test_truncates_to_the_byte_ceiling_keeping_the_end() -> None:
    """The worst case a full tail can reach is cut from the front, not the back.

    Line-count and line-length trimming alone leave
    ``LOG_TAIL_LINES * LOG_LINE_LIMIT`` bytes, which is deliberately *above* the
    ceiling — so this is the case where the byte cap has to do the work.
    """
    module = _log_format_module()

    assert module.LOG_TAIL_LINES * module.LOG_LINE_LIMIT > module.LOG_TEXT_LIMIT

    raw = '\n'.join(
        chr(ord('a') + index % 26) * module.LOG_LINE_LIMIT
        for index in range(module.LOG_TAIL_LINES * 4)
    )
    result = module.format_logs(raw)

    assert len(result.encode('utf-8')) <= module.LOG_TEXT_LIMIT + len('…\n'.encode())
    assert result.startswith('…\n')
    # The newest line survives intact; the oldest is what got dropped.
    last = chr(ord('a') + (module.LOG_TAIL_LINES * 4 - 1) % 26)
    assert result.endswith(last * module.LOG_LINE_LIMIT)


def test_long_lines_are_clipped() -> None:
    """A single runaway line cannot crowd out the rest of the tail."""
    module = _log_format_module()

    raw = 'a' * 5000 + '\nshort'
    result = module.format_logs(raw)

    assert result.splitlines()[0] == 'a' * module.LOG_LINE_LIMIT
    assert result.splitlines()[-1] == 'short'


def test_strips_ansi_colour_codes() -> None:
    """Containers colorize; nothing downstream interprets ANSI."""
    module = _log_format_module()

    result = module.format_logs('\x1b[31mERROR\x1b[0m boom')

    assert result == 'ERROR boom'


def test_multibyte_truncation_does_not_raise() -> None:
    """Slicing bytes can land mid-codepoint; the partial head is dropped."""
    module = _log_format_module()

    # Enough full-width lines to push past the ceiling, so the byte slice runs
    # and lands mid-codepoint on a 3-byte character.
    raw = '\n'.join(['日' * module.LOG_LINE_LIMIT] * (module.LOG_TAIL_LINES * 2))
    result = module.format_logs(raw)

    assert len(result.encode('utf-8')) <= module.LOG_TEXT_LIMIT + len('…\n'.encode())
    # Whatever survived is decodable and is genuinely the tail.
    assert result.endswith('日')


def test_empty_input_yields_empty_text() -> None:
    """The caller substitutes the placeholder; the formatter stays honest."""
    module = _log_format_module()

    assert module.format_logs('') == ''
    assert module.format_logs('\n\n  \n') == ''
