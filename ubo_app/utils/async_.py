# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from threading import current_thread
from typing import TYPE_CHECKING, Awaitable, Callable, TypeVarTuple, Unpack

from typing_extensions import TypeVar

from ubo_app.logging import logger

if TYPE_CHECKING:
    from asyncio import Future, Handle

    from redux.basic_types import TaskCreatorCallback


background_tasks: set[Handle] = set()


def create_task(
    awaitable: Awaitable,
    callback: TaskCreatorCallback | None = None,
) -> Handle:
    async def wrapper() -> None:
        from ubo_app.load_services import UboServiceThread

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

    import ubo_app.utils.loop

    handle = ubo_app.utils.loop._create_task(wrapper(), callback)  # noqa: SLF001
    background_tasks.add(handle)
    return handle


T = TypeVar('T', infer_variance=True)
Ts = TypeVarTuple('Ts')


def run_in_executor(
    executor: object,
    task: Callable[[Unpack[Ts]], T],
    *args: Unpack[Ts],
) -> Future[T]:
    import ubo_app.utils.loop

    return ubo_app.utils.loop._run_in_executor(executor, task, *args)  # noqa: SLF001
