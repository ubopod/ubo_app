"""Background running mixin abstract base class."""

from __future__ import annotations

import abc
import threading
from typing import TYPE_CHECKING, final

from ubo_app.colors import DANGER_COLOR
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.notifications import Notification, NotificationsAddAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error

if TYPE_CHECKING:
    import asyncio


class BackgroundRunningMixin(abc.ABC):
    """Base class for third-party background running engines."""

    name: str
    label: str

    def __init__(
        self,
        *,
        name: str,
        label: str,
    ) -> None:
        """Initialize `BackgroundRunningMixin`."""
        self.name = name
        self.label = label
        self._task = None
        self._run_lock = threading.Lock()
        self._is_running: bool = False
        super().__init__()

    @final
    def _task_done_callback(self, task: asyncio.Task[None]) -> None:
        self._is_running = False
        self._task = None
        if not task.cancelled() and task.exception():
            logger.exception(
                'An error occurred while running the engine',
                extra={
                    'engine_name': self.name,
                },
                exc_info=task.exception(),
            )
            report_service_error(exception=task.exception())
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title=self.name,
                        content=(
                            f'An error occurred while running "{self.name}".'
                            'Please check the logs for more details.'
                        ),
                        color=DANGER_COLOR,
                    ),
                ),
            )

    @final
    def _set_task(self, task: asyncio.Task[None]) -> None:
        self._task = task
        self._task.add_done_callback(self._task_done_callback)

    async def _run(self) -> None:
        raise NotImplementedError

    def run(self) -> bool:
        """Run the engine if it is not already running."""
        with self._run_lock:
            if self._is_running:
                return True
            self._is_running = True
            create_task(
                self._run(),
                callback=self._set_task,
                name='VoskEngine.run',
            )
            return True

    @final
    def stop(self) -> None:
        """Stop the engine if it is running."""
        if not self._task:
            return
        self._task.cancel()

    def should_be_running(self) -> bool:
        """Check if the engine should be running."""
        return False

    @final
    def decide_running_state(self) -> None:
        """Decide whether the engine should be running based on the state."""
        if self.should_be_running():
            self.run()
        else:
            self.stop()
