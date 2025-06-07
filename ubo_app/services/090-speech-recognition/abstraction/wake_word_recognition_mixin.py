"""Wake word recognition mixin abstract base class."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, final

from typing_extensions import override

from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue

from .base_class import BaseSpeechRecognitionEngine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from ubo_app.store.services.speech_recognition import (
        SpeechRecognitionEngineName,
    )


class WakeWordRecognitionMixin(BaseSpeechRecognitionEngine, abc.ABC):
    """Mixin for wake word detection functionality."""

    wake_words: Sequence[str] | None = None

    @override
    def __init__(
        self,
        *,
        name: SpeechRecognitionEngineName,
        label: str,
    ) -> None:
        """Initialize wake word recognition mixin."""
        self.woke_word_recognitions_queue: AsyncEvictingQueue[str | None] = (
            AsyncEvictingQueue(maxsize=5)
        )
        super().__init__(name=name, label=label)

    def set_wake_words(self, wake_words: Sequence[str] | None) -> None:
        """Set the wake words for detection."""
        self.wake_words = wake_words

        self.decide_running_state()

    @final
    async def wake_word_recogntions(self) -> AsyncGenerator[str, None]:
        """Yield recognized wake words."""
        while wake_word := await self.woke_word_recognitions_queue.get():
            yield wake_word

    @override
    async def report(self, result: str) -> None:
        """Report the recognized speech and check for wake words."""
        for wake_word in self.wake_words or []:
            if wake_word.lower() in result.lower():
                await self.woke_word_recognitions_queue.put(wake_word)
                break
        else:
            await super().report(result)

    @override
    def should_be_running(self) -> bool:
        """Check if the wake word engine should be running."""
        return bool(self.wake_words) or super().should_be_running()
