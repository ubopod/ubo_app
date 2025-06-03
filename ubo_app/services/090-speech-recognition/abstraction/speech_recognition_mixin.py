"""Speech recognition mixin abstract base class."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, final, overload

from typing_extensions import override

from abstraction.base_class import BaseSpeechRecognitionEngine
from ubo_app.logger import logger
from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from ubo_app.store.services.speech_recognition import (
        SpeechRecognitionEngineName,
    )


class Recognition:
    """Base class for recognition data."""

    def __init__(self, engine_name: SpeechRecognitionEngineName) -> None:
        """Initialize a recognition instance."""
        self.audio = b''
        self.text = ''
        self.engine_name = engine_name

    @final
    def append_voice(self, data: bytes) -> None:
        """Append a chunk of audio data to the ongoing voice recognition."""
        self.audio += data

    @final
    def append_text(self, text: str) -> None:
        """Append text to the ongoing voice recognition."""
        if self.text:
            self.text += ' '
        self.text += text


class SpeechRecognition(Recognition):
    """Recognition data for ongoing speech recognition."""

    def __init__(
        self,
        name: SpeechRecognitionEngineName,
        *,
        end_phrase: str,
    ) -> None:
        """Initialize a recognition instance."""
        self.end_phrase = end_phrase
        super().__init__(name)


class PhraseRecognition(Recognition):
    """Recognition data for ongoing phrase recognition."""

    def __init__(
        self,
        engine_name: SpeechRecognitionEngineName,
        *,
        phrases: Sequence[str],
    ) -> None:
        """Initialize a recognition instance."""
        self.phrases = phrases
        super().__init__(engine_name)


class SpeechRecognitionMixin(BaseSpeechRecognitionEngine, abc.ABC):
    """Base class for speech recognition engines."""

    speech_engine_name: SpeechRecognitionEngineName

    @override
    def __init__(self, *, name: SpeechRecognitionEngineName, label: str) -> None:
        """Initialize speech recognition engine."""
        self.ongoing_recognition: Recognition | None = None
        self.speech_recognitions_queue: AsyncEvictingQueue[Recognition | None] = (
            AsyncEvictingQueue(maxsize=5)
        )
        super().__init__(name=name, label=label)

    def should_be_running(self) -> bool:
        """Check if the speech recognition engine should be running."""
        return self.ongoing_recognition is not None or super().should_be_running()

    @overload
    async def activate_speech_recognition(
        self,
        *,
        end_phrase: str,
    ) -> None: ...
    @overload
    async def activate_speech_recognition(
        self,
        *,
        phrases: Sequence[str],
    ) -> None: ...
    @final
    async def activate_speech_recognition(
        self,
        *,
        end_phrase: str | None = None,
        phrases: Sequence[str] | None = None,
    ) -> None:
        """Activate speech recognition."""
        if self.ongoing_recognition is not None:
            msg = 'Speech recognition is already active.'
            raise RuntimeError(msg)
        if end_phrase is not None:
            self.ongoing_recognition = SpeechRecognition(
                self.speech_engine_name,
                end_phrase=end_phrase,
            )
        elif phrases is not None:
            self.ongoing_recognition = PhraseRecognition(
                self.speech_engine_name,
                phrases=phrases,
            )

        self.decide_running_state()

    @final
    async def deactivate_speech_recognition(self) -> None:
        """Deactivate the ongoing speech recognition."""
        self.ongoing_recognition = None
        await self.speech_recognitions_queue.put(None)

        self.decide_running_state()

    @final
    async def _complete_speech_recognition(self) -> None:
        """Complete the ongoing speech recognition."""
        if self.ongoing_recognition is None:
            msg = 'Speech recognition is not active.'
            raise RuntimeError(msg)
        await self.speech_recognitions_queue.put(self.ongoing_recognition)

    @override
    async def report(self, result: str) -> None:
        """Report the recognized speech."""
        logger.info(
            'Speech recognized',
            extra={
                'result': result,
                'engine_name': self.name,
            },
        )
        if self.ongoing_recognition:
            if isinstance(self.ongoing_recognition, SpeechRecognition):
                indices = [
                    result.lower().index(term)
                    for term in self.ongoing_recognition.end_phrase.split()
                    if term in result.lower()
                ]
                if len(indices) == len(
                    self.ongoing_recognition.end_phrase.split(),
                ) and indices == sorted(indices):
                    logger.info(
                        'End phrase detected, completing recognition',
                        extra={
                            'engine_name': self.name,
                            'end_phrase': self.ongoing_recognition.end_phrase,
                        },
                    )
                    self.ongoing_recognition.append_text(result[: indices[0]])
                    await self._complete_speech_recognition()
                else:
                    self.ongoing_recognition.append_text(result)
            elif isinstance(self.ongoing_recognition, PhraseRecognition):
                for phrase in self.ongoing_recognition.phrases:
                    if phrase.lower() in result.lower():
                        logger.info(
                            'Recognized phrase detected, completing recognition',
                            extra={
                                'engine_name': self.name,
                                'phrase': phrase,
                            },
                        )
                        self.ongoing_recognition.append_text(phrase)
                        await self._complete_speech_recognition()
                        break
        else:
            await super().report(result)

    @final
    async def speech_recognitions(self) -> AsyncGenerator[Recognition, None]:
        """Yield recognized speeches."""
        while recognition := await self.speech_recognitions_queue.get():
            yield recognition
