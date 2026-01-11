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

    # Freeze detection thresholds
    TICK_GAP_THRESHOLD = 1.0  # Log if gap between ticks exceeds 1 second
    CALLBACK_DURATION_THRESHOLD = 0.5  # Log if callback takes > 500ms
    HEARTBEAT_INTERVAL = 30.0  # Periodic health log every 30 seconds

    def __init__(self: Scheduler) -> None:
        """Initialize the scheduler."""
        super().__init__()
        self.name = 'Scheduler Thread'
        self.stopped = False
        self._callbacks: list[tuple[Callable[[], None], float]] = []
        self.loop = asyncio.new_event_loop()
        self.loop.set_exception_handler(loop_exception_handler)
        self.tasks: set[asyncio.Task] = set()
        # Freeze detection state
        self._last_tick_time: float = 0.0
        self._last_heartbeat_time: float = 0.0
        self._tick_count: int = 0
        self._freeze_count: int = 0
        self._start_time: float = 0.0  # Set when first tick runs

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
        import time

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

        # Freeze detection: check gap since last tick
        current_time = time.time()
        tick_gap = (
            current_time - self._last_tick_time if self._last_tick_time > 0 else 0
        )

        try:
            start_time = time.time()
            callback()
            callback_duration = time.time() - start_time

            self._tick_count += 1
            self._last_tick_time = time.time()

            # Track when scheduler started (first tick)
            if self._start_time == 0:
                self._start_time = current_time

            # Log only when freeze detected (tick gap > threshold)
            if tick_gap > self.TICK_GAP_THRESHOLD:
                from ubo_app.logger import logger

                self._freeze_count += 1
                logger.warning(
                    'Scheduler freeze detected',
                    extra={
                        'tick_gap_seconds': round(tick_gap, 2),
                        'callback_duration_ms': round(callback_duration * 1000, 1),
                        'freeze_count': self._freeze_count,
                        'tick_count': self._tick_count,
                    },
                )

            # Log if callback itself took too long
            elif callback_duration > self.CALLBACK_DURATION_THRESHOLD:
                from ubo_app.logger import logger

                logger.warning(
                    'Scheduler callback slow',
                    extra={
                        'callback_duration_ms': round(callback_duration * 1000, 1),
                        'tick_count': self._tick_count,
                    },
                )

            # Periodic heartbeat (every 30s) - confirms scheduler is alive
            elif current_time - self._last_heartbeat_time > self.HEARTBEAT_INTERVAL:
                from ubo_app.logger import logger

                self._last_heartbeat_time = current_time
                logger.debug(
                    'Scheduler heartbeat',
                    extra={
                        'tick_count': self._tick_count,
                        'freeze_count': self._freeze_count,
                    },
                )

        except Exception:
            from ubo_app.logger import logger

            logger.exception('Error in store heartbeat callback')

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
        import time

        from ubo_app.logger import logger

        self.stopped = True

        # Log summary on shutdown
        if self._start_time > 0:
            runtime = time.time() - self._start_time
            expected_ticks = int(runtime / 0.025)
            efficiency = (
                round(self._tick_count / expected_ticks * 100, 1)
                if expected_ticks > 0
                else 0
            )
            logger.debug(
                'Scheduler shutdown summary',
                extra={
                    'runtime_seconds': round(runtime, 1),
                    'tick_count': self._tick_count,
                    'expected_ticks': expected_ticks,
                    'efficiency_percent': efficiency,
                    'freeze_count': self._freeze_count,
                },
            )

        await asyncio.sleep(0.05)
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(asyncio.gather(*self.tasks), timeout=0.1)
        self.tasks.clear()
        self.loop.stop()

    def stop(self: Scheduler) -> None:
        """Schedule the shutdown of the scheduler."""
        self.loop.call_soon_threadsafe(self.loop.create_task, self.shutdown())
