"""A group of tasks owned by one service, cancelled together on shutdown."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ubo_app.logger import logger

if TYPE_CHECKING:
    from collections.abc import Coroutine


class TaskScope:
    """A group of tasks owned by one service, cancelled together on shutdown.

    `ubo_app.utils.async_.create_task` is fire-and-forget: it returns a
    `Handle`, so anything that needs to `await` a task — or hand it to
    `asyncio.wait` — reaches for `asyncio.create_task` instead, and the task
    becomes invisible to shutdown and to error reporting. A detached one (a
    delayed flush, say) then outlives the service that started it.

    Local to this service: it exists for the MQTT session supervisor, which
    races several tasks and has to be able to tear all of them down the moment
    the connection or the settings change. Nothing else needs it, so it does
    not belong in the shared async utility.

    This keeps the awaitable `asyncio.Task` while still owning it: every task is
    tracked, an unexpected exception is logged and reported, and `aclose()`
    cancels whatever is still running. Return `aclose` from `init_service()`'s
    subscriptions and the whole group dies with the service.
    """

    def __init__(self, name: str) -> None:
        """Name the scope, for logs."""
        self._name = name
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    def create(
        self,
        coroutine: Coroutine,
        *,
        name: str | None = None,
        report_errors: bool = True,
    ) -> asyncio.Task:
        """Start a tracked task on the running loop.

        `report_errors=False` for a task whose exception the caller inspects
        itself — the MQTT session races several and re-raises the first, and
        reporting it here as well would double-count it.

        Raises:
            RuntimeError: If the scope is closing. A cancelled task's `finally`
                can reach back here, and a task started then would outlive
                `aclose` — the one thing the scope exists to prevent.

        """
        if self._closed:
            # Closing it keeps Python from also warning that it was never
            # awaited, which would bury the real message.
            coroutine.close()
            msg = f'{self._name} is closed and cannot start new tasks'
            raise RuntimeError(msg)
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(
            lambda finished: self._finished(finished, report_errors=report_errors),
        )
        if name:
            task.set_name(name)
        return task

    def _finished(self, task: asyncio.Task, *, report_errors: bool) -> None:
        self._tasks.discard(task)
        if task.cancelled() or not report_errors:
            return
        exception = task.exception()
        if exception is None:
            return
        logger.error(
            'Task failed',
            exc_info=exception,
            extra={'scope': self._name, 'task': task.get_name()},
        )
        # Late import: `error_handlers` reaches into the store, and this module
        # is imported from places that load long before it.
        from ubo_app.utils.error_handlers import report_service_error

        with contextlib.suppress(Exception):
            report_service_error(exception=exception)

    async def aclose(self) -> None:
        """Cancel everything still running and wait for it to unwind.

        The closed flag goes up *before* anything is cancelled: a cancelled
        task can start another from its `finally`, and taking a snapshot first
        would leave that one running after this returns.
        """
        self._closed = True
        while self._tasks:
            tasks = set(self._tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._tasks -= tasks
