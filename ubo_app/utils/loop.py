# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Callable, Coroutine, TypeVarTuple, Unpack

from redux import FinishEvent
from typing_extensions import TypeVar

from ubo_app.constants import DEBUG_MODE
from ubo_app.store import subscribe_event

if TYPE_CHECKING:
    from asyncio import Future, Handle


T = TypeVar('T', infer_variance=True)
Ts = TypeVarTuple('Ts')


class WorkerThread(threading.Thread):
    def __init__(self: WorkerThread) -> None:
        super().__init__()
        self.loop = asyncio.new_event_loop()
        if DEBUG_MODE:
            self.loop.set_debug(enabled=True)

    def run(self: WorkerThread) -> None:
        asyncio.set_event_loop(self.loop)

        subscribe_event(FinishEvent, self.stop)
        self.loop.run_forever()

    def run_task(self: WorkerThread, task: Coroutine) -> Handle:
        return self.loop.call_soon_threadsafe(self.loop.create_task, task)

    def run_in_executor(
        self: WorkerThread,
        executor: object,
        task: Callable[[Unpack[Ts]], T],
        *args: Unpack[Ts],
    ) -> Future[T]:
        return self.loop.run_in_executor(executor, task, *args)

    def stop(self: WorkerThread) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


thread = WorkerThread()
thread.start()


def _create_task(task: Coroutine) -> Handle:
    return thread.run_task(task)


def _run_in_executor(
    executer: object,
    task: Callable[[Unpack[Ts]], T],
    *args: Unpack[Ts],
) -> Future[T]:
    return thread.run_in_executor(executer, task, *args)


_ = _create_task, _run_in_executor
