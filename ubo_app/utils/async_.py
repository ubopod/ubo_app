# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
from threading import current_thread
from typing import TYPE_CHECKING, ParamSpec

from typing_extensions import TypeVar

if TYPE_CHECKING:
    from asyncio import Handle
    from collections.abc import Awaitable, Callable

    from redux.basic_types import TaskCreatorCallback


background_tasks: set[Handle] = set()


def create_task(
    awaitable: Awaitable,
    callback: TaskCreatorCallback | None = None,
) -> Handle:
    async def wrapper() -> None:
        from ubo_app.load_services import UboServiceThread
        from ubo_app.logging import get_logger

        logger = get_logger('ubo-app')

        if awaitable is None:
            return
        try:
            logger.verbose(
                'Starting task',
                extra={
                    'awaitable': awaitable,
                    **(
                        {'ubo_service': current_thread().name}
                        if isinstance(current_thread(), UboServiceThread)
                        else {}
                    ),
                },
            )
            await awaitable
        except Exception:
            thread = current_thread()
            logger.exception(
                'Task failed',
                extra={
                    'awaitable': awaitable,
                    **(
                        {'ubo_service': thread.path.as_posix()}
                        if isinstance(thread, UboServiceThread)
                        else {}
                    ),
                },
            )

    import ubo_app.utils.loop

    handle = ubo_app.utils.loop._create_task(wrapper(), callback)  # noqa: SLF001
    background_tasks.add(handle)
    return handle


T = TypeVar('T', infer_variance=True)
T_params = ParamSpec('T_params')


def to_thread(
    task: Callable[T_params, T],
    *args: T_params.args,
    **kwargs: T_params.kwargs,
) -> Handle:
    import ubo_app.utils.loop

    return ubo_app.utils.loop._create_task(asyncio.to_thread(task, *args, **kwargs))  # noqa: SLF001
