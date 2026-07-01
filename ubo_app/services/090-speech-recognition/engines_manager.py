"""Sync store with speech recognition engines."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypedDict, cast

from constants import INTENTS_LISTENING_TIMEOUT_SECONDS
from mic_buffer import MicBuffer
from pattern import PatternError, expand_pattern
from vosk_engine import VoskEngine

from ubo_app.constants import DATA_PATH
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioReportSampleEvent
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionIntent,
    SpeechRecognitionReportIntentDetectionAction,
    SpeechRecognitionReportIntentTimeoutAction,
    SpeechRecognitionReportSpeechAction,
    SpeechRecognitionReportWakeWordDetectionAction,
    SpeechRecognitionStatus,
    WakeMode,
    WakeWordSlot,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Sequence

    from abstraction.base_class import BaseSpeechRecognitionEngine
    from abstraction.speech_recognition_mixin import Recognition, SpeechRecognitionMixin
    from abstraction.wake_word_recognition_mixin import WakeWordRecognitionMixin
    from vosk import Model

    from ubo_app.utils.types import Subscriptions


class _Engines(TypedDict):
    wake_word: WakeWordRecognitionMixin
    speech: SpeechRecognitionMixin


def _running_engines(engines: _Engines) -> set[BaseSpeechRecognitionEngine]:
    return cast('set[BaseSpeechRecognitionEngine]', set(engines.values()))


_MIC_BUFFER_DURATION_SECONDS = 5.0
_MIC_BUFFER_OUTPUT_DIR = DATA_PATH / 'wake_phrase_recordings'


@store.with_state(
    lambda state: next(
        (
            slot.phrases
            for slot in state.speech_recognition.wake_slots
            if slot.mode is WakeMode.INTENTS
        ),
        (),
    ),
)
def _should_dump_buffer(intents_phrases: tuple[str, ...], wake_word: str) -> bool:
    """Dump the mic buffer for assistant wake/stop phrases, not intents words.

    The phrases are user-editable, so the decision reads live state rather than a
    module-level set; any intents-slot alternative counts as "don't dump".
    """
    return wake_word.casefold() not in {phrase.casefold() for phrase in intents_phrases}


def _expand_phrases(phrases: Sequence[str]) -> list[str]:
    """Expand each utterance pattern to its concrete phrases (lowercased).

    A malformed pattern falls back to the raw line as a literal so a bad pattern
    can never break recognition for the whole command set.
    """
    expanded: list[str] = []
    for phrase in phrases:
        try:
            expanded.extend(expand_pattern(phrase))
        except PatternError:
            logger.warning(
                'Invalid utterance pattern; using it as a literal phrase',
                extra={'pattern': phrase},
            )
            expanded.append(phrase)
    return [phrase.lower() for phrase in expanded]


class EnginesManager:
    """Manager for speech recognition engines."""

    def __init__(self) -> None:
        """Initialize `EnginesManager`."""
        # Vosk runs in-core for both wake-word detection and command/intent
        # speech recognition — the only engine after the Google Cloud removal.
        vosk_engine = VoskEngine()
        self.engines: _Engines = {'wake_word': vosk_engine, 'speech': vosk_engine}
        self._intents_timeout_handle: asyncio.Handle | None = None
        self.mic_buffer = MicBuffer(
            duration_seconds=_MIC_BUFFER_DURATION_SECONDS,
            output_dir=_MIC_BUFFER_OUTPUT_DIR,
        )

        store.autorun(
            lambda state: state.speech_recognition.wake_slots,
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

    def wake_word_model(self) -> Model | None:
        """Return the wake-word engine's loaded Vosk model, if any.

        Used by the wake-phrase editor to validate words against the Kaldi
        vocabulary. Returns None when the engine has no loadable model yet (e.g.
        OpenWakeWord in a later phase, or the Vosk model not downloaded).
        """
        engine = self.engines['wake_word']
        return engine.current_model() if isinstance(engine, VoskEngine) else None

    async def _queue_chunk(self, event: AudioReportSampleEvent) -> None:
        """Queue audio chunk to all running speech recognition engines.

        On-device wake-word/speech recognition only consumes the system mic;
        audio streamed from remote clients (browser, mobile) carries a non-empty
        ``audio_source`` and is ignored here.
        """
        if event.audio_source:
            return
        self.mic_buffer.add(event.timestamp, event.sample)
        for engine in _running_engines(self.engines):
            await engine.queue_audio_chunk(event.sample_speech_recognition)

    async def _sync_wake_word_engine(
        self,
        wake_slots: tuple[WakeWordSlot, ...],
    ) -> None:
        """Push the phrases of every enabled wake-word slot to the engine.

        Slots are user-editable and arrive from state, so an edit (phrases or
        enabled) re-pushes the active wake-word set to the engine live.
        """
        words = [
            phrase
            for slot in wake_slots
            if slot.enabled
            for phrase in slot.phrases
        ]
        logger.debug('Syncing wake-word engine', extra={'wake_word_count': len(words)})
        self.engines['wake_word'].set_wake_words(words or None)

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
                'intents': [intent.phrases for intent in intents],
            },
        )
        if status is SpeechRecognitionStatus.IDLE:
            self._cancel_intents_timeout()
            await self.engines['speech'].deactivate_speech_recognition()
        elif status is SpeechRecognitionStatus.INTENTS_WAITING:
            await self.engines['speech'].activate_speech_recognition(
                phrases=[
                    phrase
                    for intent in intents
                    for phrase in _expand_phrases(intent.phrases)
                ],
            )
            self._start_intents_timeout()
        elif status is SpeechRecognitionStatus.ASSISTANT_WAITING:
            self._cancel_intents_timeout()
            await self.engines['speech'].deactivate_speech_recognition()

    def _start_intents_timeout(self) -> None:
        """(Re)arm the timer that ends intent-listening if no command arrives."""
        self._cancel_intents_timeout()
        self._intents_timeout_handle = create_task(self._intents_timeout())

    def _cancel_intents_timeout(self) -> None:
        """Cancel a pending intent-listening timeout, if any."""
        if self._intents_timeout_handle is not None:
            self._intents_timeout_handle.cancel()
            self._intents_timeout_handle = None

    async def _intents_timeout(self) -> None:
        """Leave intent-listening mode after the timeout with no command."""
        await asyncio.sleep(INTENTS_LISTENING_TIMEOUT_SECONDS)
        logger.info('Intent listening timed out; returning to idle')
        store.dispatch(SpeechRecognitionReportIntentTimeoutAction())

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
                    if recognition.text.lower() in _expand_phrases(intent.phrases)
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
                    SpeechRecognitionReportIntentDetectionAction(
                        intent=intent,
                        text=recognition.text,
                    ),
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
                if _should_dump_buffer(wake_word):
                    # Persist the rolling mic buffer so the audio leading up
                    # to the trigger phrase is available for review. Run the
                    # synchronous WAV write off the event loop so the dispatch
                    # below isn't delayed.
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        self.mic_buffer.dump,
                        wake_word,
                    )
                store.dispatch(
                    SpeechRecognitionReportWakeWordDetectionAction(
                        wake_word=wake_word,
                        engine_name=self.engines['wake_word'].name,
                    ),
                )
            await asyncio.sleep(0.1)

    async def _monitor_speech_recognitions(self) -> None:
        """Monitor speech recognitions and handle them."""
        while True:
            async for recognition in self.engines['speech'].speech_recognitions():
                self.handle_speech_recognition(recognition)
            await asyncio.sleep(0.1)

    def _cleanup(self) -> None:
        """Cleanup function to stop all engines."""
        for engine in _running_engines(self.engines):
            engine.stop()
