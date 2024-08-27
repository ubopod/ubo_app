# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ParamSpec

from typing_extensions import TypeVar

if TYPE_CHECKING:
    from asyncio import Handle
    from collections.abc import Callable, Coroutine

    from redux.basic_types import TaskCreatorCallback


background_tasks = []


def create_task(
    task: Coroutine,
    callback: TaskCreatorCallback | None = None,
) -> Handle:
    import ubo_app.service

    def callback_(task: asyncio.Task) -> None:
        if callback:
            callback(task)

    handle = ubo_app.service._create_task(task, callback_)  # noqa: SLF001
    background_tasks.append(handle)
    return handle


T = TypeVar('T', infer_variance=True)
T_params = ParamSpec('T_params')


def to_thread(
    task: Callable[T_params, T],
    *args: T_params.args,
    **kwargs: T_params.kwargs,
) -> Handle:
    import ubo_app.service

    return ubo_app.service._create_task(  # noqa: SLF001
        asyncio.to_thread(task, *args, **kwargs),
    )
