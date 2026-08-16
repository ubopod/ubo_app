"""Combine async iterators into a stream of their latest values."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterable

T = TypeVar('T')


class _Done:
    """Sentinel: a source finished normally."""


class _Failure(Generic[T]):
    """Sentinel: a source raised, carrying the exception to re-raise."""

    def __init__(self, exception: BaseException) -> None:
        self.exception = exception


async def zip_latest(
    *sources: AsyncIterable[T],
    default: T | None = None,
) -> AsyncGenerator[tuple[T | None, ...], None]:
    """Yield a tuple of the most recent item produced by each source.

    Emits once per incoming item, carrying the latest value seen from every
    other source — ``default`` for a source that has not produced anything yet
    — and finishes when every source is exhausted. If a source raises, the
    exception propagates to the consumer and the remaining sources are
    cancelled.

    This replaces ``aiostream.stream.ziplatest``. `aiostream` is GPL-3.0
    licensed with no linking exception, which conflicts with this project's
    Apache-2.0 license; see NOTICE.

    The reader tasks use `asyncio.create_task` rather than
    `ubo_app.utils.async_.create_task` deliberately. Their lifetime is scoped
    to this generator, which cancels and awaits them in its `finally`, so they
    are structured concurrency rather than service background work — and the
    service variant needs a coroutine runner this generic utility cannot
    assume.
    """
    queue: asyncio.Queue[tuple[int, T | _Done | _Failure[T]]] = asyncio.Queue()
    latest: list[T | None] = [default] * len(sources)

    async def pump(index: int, source: AsyncIterable[T]) -> None:
        try:
            async for item in source:
                await queue.put((index, item))
        except Exception as exception:  # noqa: BLE001 - relayed to the consumer
            await queue.put((index, _Failure(exception)))
        else:
            await queue.put((index, _Done()))

    tasks = [
        asyncio.create_task(pump(index, source))
        for index, source in enumerate(sources)
    ]
    remaining = len(sources)
    try:
        while remaining:
            index, item = await queue.get()
            if isinstance(item, _Done):
                remaining -= 1
                continue
            if isinstance(item, _Failure):
                raise item.exception
            latest[index] = item
            yield tuple(latest)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
