# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ParamSpec

from typing_extensions import TypeVar

from ubo_app.utils.service import get_coroutine_runner

if TYPE_CHECKING:
    from asyncio import Handle
    from collections.abc import Callable, Coroutine

    from redux.basic_types import TaskCreatorCallback

    from ubo_app.utils.types import CoroutineRunner


tasks: list[Handle] = []


def create_task(
    task: Coroutine,
    callback: TaskCreatorCallback | None = None,
    coroutine_runner: CoroutineRunner | None = None,
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

    if coroutine_runner is None:
        coroutine_runner = get_coroutine_runner()

    handle = (
        coroutine_runner(result, callback_) if callback else coroutine_runner(result)
    )

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
    coroutine_runner = get_coroutine_runner()

    return coroutine_runner(asyncio.to_thread(task, *args, **kwargs))


def to_thread_with_coroutine_runner(
    task: Callable[T_params, T],
    coroutine_runner: CoroutineRunner,
    *args: T_params.args,
    **kwargs: T_params.kwargs,
) -> Handle:
    return coroutine_runner(asyncio.to_thread(task, *args, **kwargs))
