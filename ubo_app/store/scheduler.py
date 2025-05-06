"""Scheduler for Redux store."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import TYPE_CHECKING

from ubo_app.utils.error_handlers import loop_exception_handler

if TYPE_CHECKING:
    from collections.abc import Callable


class Scheduler(threading.Thread):
    """Store scheduler running in a separate thread."""

    def __init__(self: Scheduler) -> None:
        """Initialize the scheduler."""
        super().__init__()
        self.name = 'Scheduler Thread'
        self.stopped = False
        self._callbacks: list[tuple[Callable[[], None], float]] = []
        self.loop = asyncio.new_event_loop()
        self.loop.set_exception_handler(loop_exception_handler)
        self.tasks: set[asyncio.Task] = set()

    def run(self: Scheduler) -> None:
        """Run the scheduler."""
        from ubo_app.logger import logger

        logger.info('Starting scheduler async loop')
        try:
            self.loop.run_forever()
        except:  # noqa: E722
            logger.info('Scheduler ran into an error and stopped', exc_info=True)
        else:
            logger.info('Scheduler stopped gracefully')

    def set(
        self: Scheduler,
        callback: Callable[[], None],
        *,
        interval: bool,
        delay_duration: float | None = None,
    ) -> None:
        """Start the scheduler."""
        self.loop.call_soon_threadsafe(
            self.loop.create_task,
            self.call_callback(
                callback,
                interval=interval,
                delay_duration=delay_duration,
            ),
        )

    async def call_callback(
        self: Scheduler,
        callback: Callable[[], None],
        *,
        interval: bool,
        delay_duration: float | None,
        last_call: float | None = None,
    ) -> None:
        """Call the callback function."""
        if self.stopped:
            return
        if delay_duration is None:
            delay_duration = 0.025
        now = self.loop.time()
        if last_call is None:
            last_call = now
        required_sleep = max(
            delay_duration - max(now - last_call - delay_duration, 0),
            0,
        )
        await asyncio.sleep(required_sleep)
        callback()
        if interval:
            self.tasks.add(
                self.loop.create_task(
                    self.call_callback(
                        callback,
                        interval=interval,
                        delay_duration=delay_duration,
                        last_call=now,
                    ),
                ),
            )
            self.tasks = {task for task in self.tasks if not task.done()}

    async def shutdown(self: Scheduler) -> None:
        """Stop the scheduler gracefully."""
        self.stopped = True
        await asyncio.sleep(0.05)
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(asyncio.gather(*self.tasks), timeout=0.1)
        self.tasks.clear()
        self.loop.stop()

    def stop(self: Scheduler) -> None:
        """Schedule the shutdown of the scheduler."""
        self.loop.call_soon_threadsafe(self.loop.create_task, self.shutdown())
