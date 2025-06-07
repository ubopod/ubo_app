"""Asynchronous evicting queue implementation."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Generic, TypeVar

T = TypeVar('T')


class AsyncEvictingQueue(Generic[T]):
    """An asynchronous queue that evicts the oldest item when full."""

    def __init__(self, maxsize: int) -> None:
        """Initialize the queue with a maximum size."""
        self.maxsize = maxsize
        self.queue: deque[T] = deque(maxlen=maxsize)
        self._not_empty = asyncio.Condition()

    async def put(self, item: T) -> None:
        """Put an item into the queue, discarding the oldest if full."""
        async with self._not_empty:
            self.queue.append(item)
            self._not_empty.notify()

    async def get(self) -> T:
        """Get an item from the queue, waiting if necessary."""
        async with self._not_empty:
            while True:
                try:
                    return self.queue.popleft()
                except IndexError:
                    await self._not_empty.wait()

    def get_nowait(self) -> T:
        """Get an item from the queue without waiting."""
        return self.queue.popleft()

    def qsize(self) -> int:
        """Return the current size of the queue."""
        return len(self.queue)

    def empty(self) -> bool:
        """Check if the queue is empty."""
        return len(self.queue) == 0

    def full(self) -> bool:
        """Check if the queue is full."""
        return len(self.queue) >= self.maxsize
