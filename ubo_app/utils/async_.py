# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from threading import current_thread
from typing import TYPE_CHECKING, Awaitable

from ubo_app.load_services import UboServiceThread
from ubo_app.logging import logger

if TYPE_CHECKING:
    from asyncio import Task


background_tasks: set[Task] = set()


def create_task(awaitable: Awaitable) -> Task:
    async def wrapper() -> None:
        try:
            await awaitable
        except BaseException as exception:  # noqa: BLE001
            thread = current_thread()
            logger.exception(
                exception,
                extra={
                    'awaitable': awaitable,
                    **(
                        {'ubo_service': thread.path.as_posix()}
                        if isinstance(thread, UboServiceThread)
                        else {}
                    ),
                },
            )

    import _loop

    task = _loop.create_task(wrapper())
    background_tasks.add(task)
    return task
