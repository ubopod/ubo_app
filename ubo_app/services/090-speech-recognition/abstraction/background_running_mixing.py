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
from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue
from ubo_app.utils.error_handlers import report_service_error

if TYPE_CHECKING:
    import asyncio

    from ubo_app.store.services.speech_recognition import (
        SpeechRecognitionEngineName,
    )


class BackgroundRunningMixin(abc.ABC):
    """Base class for recognition engines."""

    name: SpeechRecognitionEngineName
    label: str
    input_chunks_queue: AsyncEvictingQueue[bytes]

    def __init__(
        self,
        *,
        name: SpeechRecognitionEngineName,
        label: str,
    ) -> None:
        """Initialize the recognition engine."""
        self.name = name
        self.label = label
        self.input_chunks_queue = AsyncEvictingQueue(maxsize=5)
        self._run_lock = threading.Lock()
        self._is_running: bool = False
        super().__init__()

    async def queue_audio_chunk(self, chunk: bytes) -> None:
        """Queue a chunk of audio data for processing."""
        await self.input_chunks_queue.put(chunk)

    @final
    def _task_done_callback(self, task: asyncio.Task[None]) -> None:
        self._is_running = False
        if not task.cancelled() and task.exception():
            logger.exception(
                'Speech recognition engine task failed',
                extra={
                    'engine_name': self.name,
                },
                exc_info=task.exception(),
            )
            report_service_error(exception=task.exception())
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Speech Recognition',
                        content=(
                            f'An error occurred while running the "{self.name}" '
                            'speech recognition engine. Please check the logs '
                            'for more details.'
                        ),
                        color=DANGER_COLOR,
                    ),
                ),
            )

    @final
    def _set_task(self, task: asyncio.Task[None]) -> None:
        self._task = task
        self._task.add_done_callback(self._task_done_callback)

    @abc.abstractmethod
    async def _run(self) -> None:
        """Run the recognition engine."""
        msg = 'This method should be implemented by subclasses.'
        raise NotImplementedError(msg)

    def run(self) -> None:
        """Run the recognition engine in a background task."""
        with self._run_lock:
            if self._is_running:
                return
            self._is_running = True
            create_task(
                self._run(),
                callback=self._set_task,
                name='VoskEngine.run',
            )

    @final
    def stop(self) -> None:
        """Stop the recognition engine."""
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

    async def report(self, result: str) -> None:
        """Report the recognized speech."""
        logger.debug(
            'Unprocessed speech recognized',
            extra={
                'result': result,
                'engine_name': self.name,
            },
        )
