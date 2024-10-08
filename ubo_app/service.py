# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import contextlib
import threading
import traceback
from typing import TYPE_CHECKING, TypeVarTuple

from typing_extensions import TypeVar

service_id: str
service_uid: str
name: str
label: str
path: str

if TYPE_CHECKING:
    from asyncio import Handle
    from asyncio.tasks import Task
    from collections.abc import Callable, Coroutine

    from redux.basic_types import TaskCreatorCallback


T = TypeVar('T', infer_variance=True)
Ts = TypeVarTuple('Ts')


class WorkerThread(threading.Thread):
    loop: asyncio.AbstractEventLoop

    def __init__(self: WorkerThread) -> None:
        super().__init__()

        self.is_finished = threading.Event()

    def run(self: WorkerThread) -> None:
        if not self.loop.is_running():
            self.loop.run_forever()

    def run_task(
        self: WorkerThread,
        coroutine: Coroutine,
        callback: Callable[[Task], None] | None = None,
    ) -> Handle:
        from ubo_app.constants import DEBUG_MODE_TASKS

        def task_wrapper(stack: str) -> None:
            task = self.loop.create_task(coroutine)
            if DEBUG_MODE_TASKS:
                from ubo_app.error_handlers import STACKS

                STACKS[task] = stack
            if callback:
                callback(task)

        return self.loop.call_soon_threadsafe(
            task_wrapper,
            ''.join(traceback.format_stack()[:-3]) if DEBUG_MODE_TASKS else '',
        )

    async def shutdown(self: WorkerThread) -> None:
        from ubo_app.constants import MAIN_LOOP_GRACE_PERIOD
        from ubo_app.logging import logger

        logger.info('Stopping worker thread')

        while True:
            tasks = [
                task
                for task in asyncio.all_tasks(self.loop)
                if task is not asyncio.current_task(self.loop)
                and task.cancelling() == 0
                and not task.done()
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
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(
                    asyncio.gather(
                        *tasks,
                        return_exceptions=True,
                    ),
                    timeout=MAIN_LOOP_GRACE_PERIOD,
                )
            await asyncio.sleep(0.1)

        logger.debug('Stopping event loop', extra={'thread_': self})
        self.loop.stop()
        self.is_finished.set()

    def stop(self: WorkerThread) -> None:
        self.loop.call_soon_threadsafe(self.loop.create_task, self.shutdown())


worker_thread = WorkerThread()


def start_event_loop_thread(loop: asyncio.AbstractEventLoop) -> None:
    from ubo_app.error_handlers import loop_exception_handler

    loop.set_exception_handler(loop_exception_handler)

    worker_thread.loop = loop
    worker_thread.start()

    from redux.basic_types import FinishEvent

    from ubo_app.store.main import store

    def stop() -> None:
        unsubscribe()
        worker_thread.stop()

    unsubscribe = store.subscribe_event(FinishEvent, stop)


def _create_task(
    task: Coroutine,
    callback: TaskCreatorCallback | None = None,
) -> Handle:
    return worker_thread.run_task(task, callback)


_ = _create_task
