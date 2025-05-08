# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import contextlib
import threading
import traceback
from typing import TYPE_CHECKING, TypeVarTuple

from typing_extensions import TypeVar

if TYPE_CHECKING:
    from pathlib import Path

service_id: str
service_uid: str
name: str
label: str
path: Path

if TYPE_CHECKING:
    from asyncio import Handle
    from collections.abc import Coroutine

    from redux.basic_types import TaskCreatorCallback


T = TypeVar('T', infer_variance=True)
Ts = TypeVarTuple('Ts')


class WorkerThread(threading.Thread):
    loop: asyncio.AbstractEventLoop

    def __init__(self: WorkerThread) -> None:
        super().__init__()
        self.name = 'Worker Thread'

        self.is_finished = threading.Event()
        self.is_started = threading.Event()

    def run(self: WorkerThread) -> None:
        if not self.loop.is_running():
            self.is_started.set()
            self.loop.run_forever()

    def run_coroutine(
        self: WorkerThread,
        coroutine: Coroutine,
        callback: TaskCreatorCallback | None = None,
    ) -> Handle:
        from ubo_app.constants import DEBUG_TASKS

        def task_wrapper(stack: str) -> None:
            task = self.loop.create_task(coroutine)
            if DEBUG_TASKS:
                from ubo_app.utils.error_handlers import STACKS

                STACKS[task] = stack
            if callback:
                callback(task)

        task_wrapper.__name__ = f'run_task:{coroutine.__name__}'
        task_wrapper.__qualname__ = f'run_task:{coroutine.__qualname__}'

        return self.loop.call_soon_threadsafe(
            task_wrapper,
            ''.join(traceback.format_stack()[:-3]) if DEBUG_TASKS else '',
        )

    async def shutdown(self: WorkerThread) -> None:
        from ubo_app.constants import MAIN_LOOP_GRACE_PERIOD
        from ubo_app.logger import logger

        logger.info('Stopping the worker thread')

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

        logger.debug('Stopping event loop of the worker thread')
        self.loop.stop()
        self.is_finished.set()
        logger.info('The worker thread is done')

    def stop(self: WorkerThread) -> None:
        self.loop.call_soon_threadsafe(self.loop.create_task, self.shutdown())


worker_thread = WorkerThread()


def start_event_loop_thread(loop: asyncio.AbstractEventLoop) -> None:
    from ubo_app.utils.error_handlers import loop_exception_handler

    loop.set_exception_handler(loop_exception_handler)

    worker_thread.loop = loop
    worker_thread.start()

    from redux.basic_types import FinishEvent

    from ubo_app.store.main import store

    store.subscribe_event(FinishEvent, worker_thread.stop)

    worker_thread.is_started.wait()


def run_coroutine(
    coroutine: Coroutine,
    callback: TaskCreatorCallback | None = None,
) -> Handle:
    return worker_thread.run_coroutine(coroutine, callback)
