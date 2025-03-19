# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
from threading import current_thread
from typing import TYPE_CHECKING, ParamSpec

from typing_extensions import TypeVar

if TYPE_CHECKING:
    from asyncio import Handle
    from collections.abc import Callable, Coroutine

    from redux.basic_types import TaskCreatorCallback


tasks: list[Handle] = []


def get_task_runner() -> Callable[..., Handle]:
    import ubo_app.service
    from ubo_app.service_thread import UboServiceThread

    thread = current_thread()

    if isinstance(thread, UboServiceThread):
        return thread.run_task

    return ubo_app.service.run_task


def create_task(
    task: Coroutine,
    callback: TaskCreatorCallback | None = None,
) -> Handle:
    def callback_(task: asyncio.Task) -> None:
        if callback:
            callback(task)

    handle: Handle | None = None
    signal = asyncio.Event()

    async def wrapper() -> None:
        try:
            await task
        finally:
            await signal.wait()
            if handle in tasks:
                tasks.remove(handle)

    result = wrapper()
    result.__name__ = f'task_wrapper_coroutine:{task.__name__}'
    result.__qualname__ = f'task_wrapper_coroutine:{task.__qualname__}'

    task_runner = get_task_runner()

    handle = task_runner(result, callback_) if callback else task_runner(result)

    tasks.append(handle)
    signal.set()
    return handle


T = TypeVar('T', infer_variance=True)
T_params = ParamSpec('T_params')


def to_thread(
    task: Callable[T_params, T],
    *args: T_params.args,
    **kwargs: T_params.kwargs,
) -> Handle:
    task_runner = get_task_runner()

    return task_runner(asyncio.to_thread(task, *args, **kwargs))
