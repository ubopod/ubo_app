"""Base class for speech recognition engines."""

from __future__ import annotations

import abc

from typing_extensions import override

from ubo_app.engines.abstraction.background_running_mixin import BackgroundRunningMixin
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    WakeEngineSetEnabledAction,
    WakeWordEngineName,
)
from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue

# Valid wake-engine name values, for guarding the disable-on-failure dispatch.
_WAKE_ENGINE_NAMES = {member.value for member in WakeWordEngineName}


class BaseSpeechRecognitionEngine(BackgroundRunningMixin):
    """Base class for speech recognition engines."""

    @override
    def __init__(self, *, label: str | None = None) -> None:
        """Initialize speech recognition engine."""
        self.input_queue: AsyncEvictingQueue[bytes] = AsyncEvictingQueue(maxsize=5)
        super().__init__(label=label)

    async def queue_audio_chunk(self, chunk: bytes) -> None:
        """Queue a chunk of audio data for processing."""
        await self.input_queue.put(chunk)

    @override
    def run(self) -> bool:
        if not super().run():
            # The engine can't start (e.g. its model isn't set up) — disable the
            # whole engine so the manager stops feeding it and the UI reflects it.
            # Only wake engines have a config to disable; a speech-only engine
            # whose name isn't a WakeWordEngineName is skipped rather than crashing
            # the failure path with a ValueError.
            if self.name in _WAKE_ENGINE_NAMES:
                store.dispatch(
                    WakeEngineSetEnabledAction(
                        engine=WakeWordEngineName(self.name),
                        enabled=False,
                    ),
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
