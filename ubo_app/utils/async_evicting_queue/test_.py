"""Test for AsyncEvictingQueue."""

from __future__ import annotations

import asyncio

from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue


async def test_async_evicting_queue() -> None:
    """Run tests for the AsyncEvictingQueue."""
    q = AsyncEvictingQueue(3)

    # Test 1: Basic put and get
    await q.put(1)
    assert await q.get() == 1, 'Basic put/get failed'
    assert q.empty(), 'Queue should be empty'

    # Test 2: Async wait on empty queue
    async def delayed_put() -> None:
        await asyncio.sleep(0.1)
        await q.put(2)

    task = asyncio.create_task(delayed_put())
    assert await q.get() == 2, 'Async wait on get failed'
    await task

    # Test 3: Overflow discards oldest
    await q.put(1)
    await q.put(2)
    await q.put(3)
    await q.put(4)  # Should discard 1
    assert q.qsize() == 3, 'Queue size should be 3'
    assert await q.get() == 2, 'Oldest item not discarded'

    # Test 4: Full and empty checks
    await q.put(5)
    await q.put(6)
    assert q.full(), 'Queue should be full'
    await q.get()
    await q.get()
    await q.get()
    assert q.empty(), 'Queue should be empty'
