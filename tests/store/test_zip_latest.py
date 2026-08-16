"""Tests for `zip_latest`, the in-tree replacement for `aiostream.ziplatest`.

The engines' download-progress path (`ubo_app/engines/piper.py`,
`ubo_app/engines/kokoro.py`) merges two `download_file` generators with it, so
these pin the behaviours that path depends on: latest-value carry, the
`default` filler, error propagation, and no leaked reader tasks.
"""

from __future__ import annotations

import asyncio
from functools import reduce
from typing import TYPE_CHECKING, TypeVar

import pytest

from ubo_app.utils.zip_latest import zip_latest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

T = TypeVar('T')


async def _scheduled(
    schedule: Sequence[tuple[float, T | BaseException]],
) -> AsyncGenerator[T, None]:
    """Yield each item at its absolute time; raise it instead if it is an error.

    Times are well separated so ordering is deterministic — concurrent items at
    the same instant would race, and the assertions here are about semantics,
    not scheduler tie-breaks.
    """
    previous = 0.0
    for moment, item in schedule:
        await asyncio.sleep(moment - previous)
        previous = moment
        if isinstance(item, BaseException):
            raise item
        yield item


async def _collect(source: AsyncGenerator[T, None]) -> list[T]:
    return [item async for item in source]


async def _tee(
    source: AsyncGenerator[T, None],
    sink: list[T],
) -> AsyncGenerator[T, None]:
    """Pass items through, recording them, so partial output survives a raise."""
    async for item in source:
        sink.append(item)
        yield item


async def test_carries_the_latest_value_from_each_source() -> None:
    """Every incoming item emits a tuple holding the newest of each source."""
    a = _scheduled([(0.02, 'a1'), (0.06, 'a2'), (0.10, 'a3')])
    b = _scheduled([(0.04, 'b1'), (0.08, 'b2')])

    assert await _collect(zip_latest(a, b, default=None)) == [
        ('a1', None),
        ('a1', 'b1'),
        ('a2', 'b1'),
        ('a2', 'b2'),
        ('a3', 'b2'),
    ]


async def test_default_fills_sources_that_have_not_produced_yet() -> None:
    """A source silent so far reports `default`, not a missing slot."""
    a = _scheduled([(0.02, 'a1')])
    b = _scheduled([(0.04, 'b1')])

    assert await _collect(zip_latest(a, b, default='<none>')) == [
        ('a1', '<none>'),
        ('a1', 'b1'),
    ]


async def test_a_single_source_passes_through() -> None:
    """One source still yields one-tuples, not bare items."""
    a = _scheduled([(0.01, 'a1'), (0.02, 'a2')])

    assert await _collect(zip_latest(a, default=None)) == [('a1',), ('a2',)]


async def test_an_exhausted_source_does_not_end_the_others() -> None:
    """The stream runs until *every* source is done, not the first."""
    a = _scheduled([(0.02, 'a1')])
    b = _scheduled([(0.04, 'b1'), (0.06, 'b2')])

    assert await _collect(zip_latest(a, b, default=None)) == [
        ('a1', None),
        ('a1', 'b1'),
        ('a1', 'b2'),
    ]


async def test_all_sources_empty_yields_nothing() -> None:
    """No sources produce anything, so the stream ends immediately."""
    assert await _collect(zip_latest(_scheduled([]), _scheduled([]))) == []


async def test_a_failing_source_propagates_its_exception() -> None:
    """A download that fails must surface, not silently end the stream.

    This is the regression that matters most: a naive port swallows the error
    and the caller sees a *successful* short download.
    """
    a = _scheduled([(0.02, 'a1'), (0.06, RuntimeError('boom'))])
    b = _scheduled([(0.04, 'b1'), (0.08, 'b2'), (0.12, 'b3')])

    collected: list[tuple[str | None, ...]] = []
    with pytest.raises(RuntimeError, match='boom'):
        await _collect(_tee(zip_latest(a, b, default=None), collected))

    assert collected == [('a1', None), ('a1', 'b1')]


async def test_a_failure_before_any_item_propagates() -> None:
    """A source that raises before yielding still surfaces its exception."""
    a = _scheduled([(0.02, ValueError('bad'))])
    b = _scheduled([(0.04, 'b1')])

    with pytest.raises(ValueError, match='bad'):
        await _collect(zip_latest(a, b, default=None))


async def test_reader_tasks_do_not_leak_when_the_consumer_stops_early() -> None:
    """Breaking out of the loop cancels the readers rather than orphaning them."""
    before = len(asyncio.all_tasks())

    a = _scheduled([(0.01, 'a1'), (0.30, 'a2')])
    b = _scheduled([(0.02, 'b1'), (0.30, 'b2')])

    stream = zip_latest(a, b, default=None)
    async for _ in stream:
        break
    await stream.aclose()

    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) == before


async def test_reader_tasks_do_not_leak_after_a_failure() -> None:
    """The surviving source's reader is cancelled when another one raises."""
    before = len(asyncio.all_tasks())

    a = _scheduled([(0.02, RuntimeError('boom'))])
    b = _scheduled([(0.04, 'b1'), (0.50, 'b2')])

    with pytest.raises(RuntimeError, match='boom'):
        await _collect(zip_latest(a, b, default=None))

    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) == before


async def test_summed_download_progress_matches_the_engines_use() -> None:
    """The exact reduce the piper/kokoro download loops run over the output.

    Two files downloading concurrently must report combined bytes over combined
    size, and must reach exactly 1.0 when both finish.
    """
    a = _scheduled([(0.02, (50, 100)), (0.06, (100, 100))])
    b = _scheduled([(0.04, (30, 60)), (0.08, (60, 60))])

    progresses = []
    async for report in zip_latest(a, b, default=(0, None)):
        downloaded_bytes, size = reduce(
            lambda accumulator, item: (
                item[0] + accumulator[0],
                (item[1] or 1024**2) + accumulator[1],
            )
            if item
            else accumulator,
            report,
            (0, 0),
        )
        if size:
            progresses.append(min(1.0, downloaded_bytes / size))

    assert progresses[-1] == 1.0
    assert progresses == sorted(progresses), 'progress must never go backwards'
