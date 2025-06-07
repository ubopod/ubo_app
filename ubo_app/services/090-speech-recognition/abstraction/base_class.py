"""Base class for speech recognition engines."""

from __future__ import annotations

import abc

from typing_extensions import override

from ubo_app.engines.abstraction.background_running_mixin import BackgroundRunningMixin
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionEngineName,
    SpeechRecognitionSetIsAssistantActiveAction,
    SpeechRecognitionSetIsIntentsActiveAction,
)
from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue


class BaseSpeechRecognitionEngine(BackgroundRunningMixin):
    """Base class for speech recognition engines."""

    @override
    def __init__(self, *, name: SpeechRecognitionEngineName, label: str) -> None:
        """Initialize speech recognition engine."""
        self.input_queue: AsyncEvictingQueue[bytes] = AsyncEvictingQueue(maxsize=5)
        self.speech_engine_name = name
        super().__init__(name=name, label=label)

    async def queue_audio_chunk(self, chunk: bytes) -> None:
        """Queue a chunk of audio data for processing."""
        await self.input_queue.put(chunk)

    @override
    def run(self) -> bool:
        if not super().run():
            store.dispatch(
                SpeechRecognitionSetIsIntentsActiveAction(is_active=False),
                SpeechRecognitionSetIsAssistantActiveAction(is_active=False),
            )
            return False
        return True

    @abc.abstractmethod
    async def report(self, result: str) -> None:
        """Report the recognized speech."""
        logger.debug(
            'Unprocessed speech recognized',
            extra={
                'result': result,
                'engine_name': self.name,
            },
        )
