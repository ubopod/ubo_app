# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import TYPE_CHECKING, TypeVarTuple

from typing_extensions import TypeVar

if TYPE_CHECKING:
    from asyncio import Handle
    from asyncio.tasks import Task
    from collections.abc import Callable, Coroutine

    from redux.basic_types import TaskCreatorCallback


T = TypeVar('T', infer_variance=True)
Ts = TypeVarTuple('Ts')


class WorkerThread(threading.Thread):
    def __init__(self: WorkerThread) -> None:
        from redux.basic_types import FinishEvent

        from ubo_app.store import subscribe_event

        super().__init__()
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        from ubo_app.constants import DEBUG_MODE

        subscribe_event(FinishEvent, self.stop)

        if DEBUG_MODE:
            self.loop.set_debug(enabled=True)

    def run(self: WorkerThread) -> None:
        if not self.loop.is_running():
            self.loop.run_forever()

    def run_task(
        self: WorkerThread,
        task: Coroutine,
        callback: Callable[[Task], None] | None = None,
    ) -> Handle:
        def task_wrapper() -> None:
            result = self.loop.create_task(task)
            if callback:
                callback(result)

        return self.loop.call_soon_threadsafe(task_wrapper)

    async def shutdown(self: WorkerThread) -> None:
        from ubo_app.logging import logger

        logger.info('Shutting down worker thread')

        while True:
            tasks = [
                task
                for task in asyncio.all_tasks(self.loop)
                if task is not asyncio.current_task(self.loop)
            ]
            logger.debug(
                'Waiting for tasks to finish',
                extra={
                    'tasks': tasks,
                    'thread_': self,
                },
            )
            if not tasks:
                break
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(task, 1)
        logger.debug('Stopping event loop', extra={'thread_': self})
        self.loop.stop()

    def stop(self: WorkerThread) -> None:
        self.loop.call_soon_threadsafe(self.loop.create_task, self.shutdown())


thread = WorkerThread()


def setup_event_loop() -> None:
    thread.start()


def _create_task(
    task: Coroutine,
    callback: TaskCreatorCallback | None = None,
) -> Handle:
    return thread.run_task(task, callback)


_ = _create_task
