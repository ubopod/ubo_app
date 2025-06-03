"""Sync store with speech recognition engines."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypedDict, cast

from google_engine import GoogleSpeechRecognitionEngine
from vosk_engine import VoskEngine

from ubo_app.constants import ASSISTANT_END_WORD, ASSISTANT_WAKE_WORD, INTENTS_WAKE_WORD
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioReportSampleEvent
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionEngineName,
    SpeechRecognitionIntent,
    SpeechRecognitionReportIntentDetectionAction,
    SpeechRecognitionReportSpeechAction,
    SpeechRecognitionReportWakeWordDetectionAction,
    SpeechRecognitionStatus,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Sequence

    from abstraction.base_class import BaseSpeechRecognitionEngine
    from abstraction.speech_recognition_mixin import Recognition, SpeechRecognitionMixin
    from abstraction.wake_word_recognition_mixin import WakeWordRecognitionMixin

    from ubo_app.utils.types import Subscriptions


class _Engines(TypedDict):
    wake_word: WakeWordRecognitionMixin
    speech: SpeechRecognitionMixin | None


def _running_engines(engines: _Engines) -> set[BaseSpeechRecognitionEngine]:
    return cast(
        'set[BaseSpeechRecognitionEngine]',
        {engine for engine in engines.values() if engine is not None},
    )


class EnginesManager:
    """Manager for speech recognition engines."""

    def __init__(self) -> None:
        """Initialize `EnginesManager`."""
        vosk_engine = VoskEngine()
        google_engine = GoogleSpeechRecognitionEngine()
        self.engines_by_name: dict[
            SpeechRecognitionEngineName,
            SpeechRecognitionMixin,
        ] = {
            SpeechRecognitionEngineName.VOSK: vosk_engine,
            SpeechRecognitionEngineName.GOOGLE: google_engine,
        }
        self.engines: _Engines = {'wake_word': vosk_engine, 'speech': vosk_engine}
        store.autorun(lambda state: state.speech_recognition.selected_engine)(
            self._sync_selected_engine,
        )

        store.autorun(
            lambda state: (
                state.speech_recognition.is_intents_active,
                state.speech_recognition.is_assistant_active,
            ),
        )(self._sync_wake_word_engine)

        store.autorun(
            lambda state: (
                state.speech_recognition.status,
                state.speech_recognition.intents,
            ),
        )(self._sync_status)

        create_task(self._monitor_wake_word_recognitions(), name='WakeWordMonitor')
        create_task(
            self._monitor_speech_recognitions(),
            name='SpeechRecognitionMonitor',
        )

        self.subscriptions: Subscriptions = [
            store.subscribe_event(AudioReportSampleEvent, self._queue_chunk),
            self._cleanup,
        ]

    async def _queue_chunk(self, event: AudioReportSampleEvent) -> None:
        """Queue audio chunk to all running speech recognition engines."""
        for engine in _running_engines(self.engines):
            await engine.queue_audio_chunk(event.sample_speech_recognition)

    async def _sync_selected_engine(
        self,
        selected_engine: SpeechRecognitionEngineName | None,
    ) -> None:
        """Sync selected speech recognition engine."""
        if self.engines['speech'] is not None:
            await self.engines['speech'].deactivate_speech_recognition()
        self.engines['speech'] = (
            self.engines_by_name[selected_engine] if selected_engine else None
        )

    async def _sync_wake_word_engine(self, data: tuple[bool, bool]) -> None:
        """Sync wake word recognition engine based on intents and assistant status."""
        is_intents_active, is_assistant_active = data
        logger.debug(
            'Syncing recognition engine status',
            extra={
                'is_intents_active': is_intents_active,
                'is_assistant_active': is_assistant_active,
            },
        )

        if is_intents_active or is_assistant_active:
            self.engines['wake_word'].set_wake_words(
                [
                    *((INTENTS_WAKE_WORD,) if is_intents_active else ()),
                    *((ASSISTANT_WAKE_WORD,) if is_assistant_active else ()),
                ],
            )
        else:
            self.engines['wake_word'].set_wake_words(None)

    async def _sync_status(
        self,
        data: tuple[str, Sequence[SpeechRecognitionIntent]],
    ) -> None:
        """Sync speech recognition status and intents."""
        status, intents = data
        logger.debug(
            'Syncing speech recognition status',
            extra={
                'status': status,
                'intents': [intent.phrase for intent in intents],
            },
        )
        if self.engines['speech'] is None:
            logger.warning(
                'Speech recognition engine is not set, skipping status sync',
                extra={'status': status},
            )
            return
        if status is SpeechRecognitionStatus.IDLE:
            await self.engines['speech'].deactivate_speech_recognition()
        elif status is SpeechRecognitionStatus.INTENTS_WAITING:
            await self.engines['speech'].activate_speech_recognition(
                phrases=[
                    phrase.lower()
                    for intent in intents
                    for phrase in (
                        [intent.phrase]
                        if isinstance(intent.phrase, str)
                        else intent.phrase
                    )
                ],
            )
        elif status is SpeechRecognitionStatus.ASSISTANT_WAITING:
            await self.engines['speech'].activate_speech_recognition(
                end_phrase=ASSISTANT_END_WORD,
            )

    @store.with_state(
        lambda state: (
            state.speech_recognition.status,
            state.speech_recognition.intents,
        ),
    )
    def handle_speech_recognition(
        self,
        data: tuple[SpeechRecognitionStatus, Sequence[SpeechRecognitionIntent]],
        recognition: Recognition,
    ) -> None:
        """Handle speech recognitions."""
        status, intents = data
        if status is SpeechRecognitionStatus.INTENTS_WAITING:
            if intent := next(
                (
                    intent
                    for intent in intents
                    if (
                        intent.phrase.lower() == recognition.text.lower()
                        if isinstance(intent.phrase, str)
                        else recognition.text.lower()
                        in [phrase.lower() for phrase in intent.phrase]
                    )
                ),
                None,
            ):
                logger.info(
                    'Intent recognized',
                    extra={
                        'engine_name': recognition.engine_name,
                        'text': recognition.text,
                        'intent': intent,
                    },
                )
                store.dispatch(
                    SpeechRecognitionReportIntentDetectionAction(intent=intent),
                )
        elif status is SpeechRecognitionStatus.ASSISTANT_WAITING:
            logger.info(
                'Assistant command recognized',
                extra={
                    'engine_name': recognition.engine_name,
                    'text': recognition.text,
                },
            )
            store.dispatch(
                SpeechRecognitionReportSpeechAction(
                    audio=recognition.audio,
                    text=recognition.text,
                    engine_name=recognition.engine_name,
                ),
            )

    async def _monitor_wake_word_recognitions(self) -> None:
        """Monitor wake word recognitions and dispatch events."""
        while True:
            async for wake_word in self.engines['wake_word'].wake_word_recogntions():
                store.dispatch(
                    SpeechRecognitionReportWakeWordDetectionAction(wake_word=wake_word),
                )
            await asyncio.sleep(0.1)

    async def _monitor_speech_recognitions(self) -> None:
        """Monitor speech recognitions and handle them."""
        while True:
            if self.engines['speech'] is not None:
                async for recognition in self.engines['speech'].speech_recognitions():
                    self.handle_speech_recognition(recognition)
            await asyncio.sleep(0.1)

    def _cleanup(self) -> None:
        """Cleanup function to stop all engines."""
        for engine in _running_engines(self.engines):
            engine.stop()
