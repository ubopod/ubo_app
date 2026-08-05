"""Sync store with speech recognition engines."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from abstraction.wake_word_recognition_mixin import WakeTrigger
from constants import INTENTS_LISTENING_TIMEOUT_SECONDS
from matching import expand_phrases, match_recognition, stop_talking_triggers
from mic_buffer import MicBuffer
from microwakeword_engine import MicroWakeWordEngine
from openwakeword_engine import OpenWakeWordEngine
from vosk_engine import VoskEngine

from ubo_app.constants import DATA_PATH
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioReportSampleEvent
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionIntent,
    SpeechRecognitionReportIntentTimeoutAction,
    SpeechRecognitionReportWakeWordDetectionAction,
    SpeechRecognitionStatus,
    WakeMode,
    WakeWordEngineConfig,
    WakeWordEngineName,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Sequence

    from abstraction.speech_recognition_mixin import Recognition, SpeechRecognitionMixin
    from abstraction.wake_word_recognition_mixin import WakeWordRecognitionMixin
    from vosk import Model

    from ubo_app.utils.types import Subscriptions


_MIC_BUFFER_DURATION_SECONDS = 5.0
_MIC_BUFFER_OUTPUT_DIR = DATA_PATH / 'wake_phrase_recordings'

# Suppress *same-mode* detections briefly after one fires so a phrase that matches
# more than one concurrent engine (or repeats) only starts the assistant once.
# STOP_TALKING is exempt (see ``_handle_wake_detection``); the reducer's
# ``status IDLE`` guard is the secondary backstop.
_DETECTION_DEBOUNCE_SECONDS = 1.0




class EnginesManager:
    """Manager for speech recognition engines."""

    def __init__(self) -> None:
        """Initialize `EnginesManager`."""
        # Vosk serves command/intent speech recognition and is also a wake
        # engine. OpenWakeWord and microWakeWord are wake-only engines. All
        # enabled wake engines run concurrently over the same mic audio.
        # (Register Picovoice here.)
        self._vosk_engine = VoskEngine()
        self._openwakeword_engine = OpenWakeWordEngine()
        self._microwakeword_engine = MicroWakeWordEngine()
        self._wake_engines: dict[WakeWordEngineName, WakeWordRecognitionMixin] = {
            WakeWordEngineName.VOSK: self._vosk_engine,
            WakeWordEngineName.OPENWAKEWORD: self._openwakeword_engine,
            WakeWordEngineName.MICROWAKEWORD: self._microwakeword_engine,
        }
        self._speech_engine: SpeechRecognitionMixin = self._vosk_engine

        # Per-engine ``trigger id -> (value, mode)`` for the last synced config,
        # so a detection (which carries only the trigger id) resolves to its
        # phrase + mode without a store read in the hot path.
        self._trigger_index: dict[
            WakeWordEngineName,
            dict[str, tuple[str, WakeMode]],
        ] = {}
        self._enabled_engines: set[WakeWordEngineName] = set()
        # Last detection time *per mode* — debounce de-dupes the same wake (e.g.
        # a phrase matching both Vosk and OpenWakeWord) without letting one mode's
        # detection suppress another's (notably a STOP_TALKING right after a wake).
        self._last_detection_time: dict[WakeMode, float] = {}

        self._intents_timeout_handle: asyncio.Handle | None = None
        self.mic_buffer = MicBuffer(
            duration_seconds=_MIC_BUFFER_DURATION_SECONDS,
            output_dir=_MIC_BUFFER_OUTPUT_DIR,
        )

        sync_wake_engines = store.autorun(
            lambda state: (
                state.speech_recognition.wake_engines,
                state.speech_recognition.enabled_wake_modes,
                # Re-sync when the on-disk model pool changes so an engine whose
                # model arrived after startup retries its (previously failed) load.
                state.speech_recognition.openwakeword_models,
            ),
        )(self._sync_wake_engines)

        sync_status = store.autorun(
            lambda state: (
                state.speech_recognition.status,
                state.speech_recognition.intents,
                # The stop-talking phrases ride along in the armed grammar, so an
                # edit to them has to re-arm it.
                state.speech_recognition.wake_engines,
                state.speech_recognition.assistant_session_audio_source,
            ),
        )(self._sync_status)

        # ``create_task`` returns the ``call_soon_threadsafe`` scheduling handle,
        # not the long-lived ``asyncio.Task`` — so capture the real task via the
        # callback (mirroring ``BackgroundRunningMixin``) so ``_cleanup`` can
        # cancel the ``while True`` monitor loops on teardown.
        self._monitor_tasks: list[asyncio.Task] = []
        for engine_name in self._wake_engines:
            create_task(
                self._monitor_wake_engine(engine_name),
                callback=self._track_monitor_task,
                name=f'WakeWordMonitor:{engine_name.value}',
            )
        create_task(
            self._monitor_speech_recognitions(),
            callback=self._track_monitor_task,
            name='SpeechRecognitionMonitor',
        )

        self.subscriptions: Subscriptions = [
            store.subscribe_event(AudioReportSampleEvent, self._queue_chunk),
            sync_wake_engines.unsubscribe,
            sync_status.unsubscribe,
            self._cleanup,
        ]

    def wake_word_model(self) -> Model | None:
        """Return Vosk's loaded Kaldi model, if any.

        Used by the wake-phrase editor to validate words against the Vosk
        vocabulary; Vosk is always present, so this no longer depends on which
        engine is the active wake engine. Returns None until the model is loaded.
        """
        return self._vosk_engine.current_model()

    async def _queue_chunk(self, event: AudioReportSampleEvent) -> None:
        """Queue audio chunk to the speech engine and all enabled wake engines.

        On-device wake-word/speech recognition only consumes the system mic;
        audio streamed from remote clients (browser, mobile) carries a non-empty
        ``audio_source`` and is ignored here.
        """
        if event.audio_source:
            return
        self.mic_buffer.add(event.timestamp, event.sample)
        targets = {
            self._speech_engine,
            *(self._wake_engines[name] for name in self._enabled_engines),
        }
        for engine in targets:
            await engine.queue_audio_chunk(event.sample_speech_recognition)

    async def _sync_wake_engines(
        self,
        data: tuple[
            tuple[WakeWordEngineConfig, ...],
            tuple[WakeMode, ...],
            tuple[str, ...],
        ],
    ) -> None:
        """Push each enabled engine its active triggers; stop the rest.

        Engines and triggers are user-editable and arrive from state, so any edit
        re-pushes the active trigger set live and (dis)engages the engine. A trigger
        whose mode is switched off in ``enabled_wake_modes`` is dropped; STOP_TALKING
        (Silence) has no switch and always rides along.
        """
        configs, enabled_wake_modes, _openwakeword_models = data
        enabled: set[WakeWordEngineName] = set()
        index: dict[WakeWordEngineName, dict[str, tuple[str, WakeMode]]] = {}
        for config in configs:
            engine = self._wake_engines.get(config.engine)
            if engine is None:
                # Unknown / not-yet-registered engine (e.g. future Picovoice).
                continue
            active = [
                trigger
                for trigger in config.triggers
                if trigger.mode is WakeMode.STOP_TALKING
                or trigger.mode in enabled_wake_modes
            ]
            if config.enabled and active:
                enabled.add(config.engine)
                engine.set_triggers(
                    [
                        WakeTrigger(
                            id=trigger.id,
                            value=trigger.value,
                            sensitivity=trigger.sensitivity,
                        )
                        for trigger in active
                    ],
                )
                index[config.engine] = {
                    trigger.id: (trigger.value, trigger.mode) for trigger in active
                }
            else:
                engine.set_triggers(None)
                index[config.engine] = {}
        self._enabled_engines = enabled
        self._trigger_index = index
        logger.debug(
            'Synced wake engines',
            extra={'enabled': [name.value for name in enabled]},
        )

    async def _sync_status(
        self,
        data: tuple[
            str,
            Sequence[SpeechRecognitionIntent],
            Sequence[WakeWordEngineConfig],
            str,
        ],
    ) -> None:
        """Arm or disarm the Vosk grammar for the current listening status.

        ``INTENTS_WAITING`` is the standalone command window (10 s timeout);
        ``ASSISTANT_WAITING`` is stage-1 matching riding alongside a quick-chat
        session, whose lifetime is the assistant's ``is_listening`` rather than a
        timeout of ours. Both listen for the same phrases.
        """
        status, intents, wake_engines, assistant_audio_source = data
        logger.debug(
            'Syncing speech recognition status',
            extra={
                'status': status,
                'intents': [intent.phrases for intent in intents],
                'assistant_audio_source': assistant_audio_source,
            },
        )

        is_remote_session = (
            status is SpeechRecognitionStatus.ASSISTANT_WAITING
            and bool(assistant_audio_source)
        )
        if status is SpeechRecognitionStatus.IDLE or is_remote_session:
            # A remote-mic session's audio is dropped by ``_queue_chunk``, so Vosk
            # can never hear it — leave the grammar disarmed rather than pretend.
            self._cancel_intents_timeout()
            await self._speech_engine.deactivate_speech_recognition()
            return

        # ``activate_speech_recognition`` refuses to re-enter while a recognition
        # is ongoing, and this autorun re-fires on every intent / trigger edit.
        await self._speech_engine.deactivate_speech_recognition()
        await self._speech_engine.activate_speech_recognition(
            phrases=[
                *(
                    phrase
                    for intent in intents
                    for phrase in expand_phrases(intent.phrases)
                ),
                *stop_talking_triggers(wake_engines),
            ],
        )

        if status is SpeechRecognitionStatus.INTENTS_WAITING:
            self._start_intents_timeout()
        else:
            self._cancel_intents_timeout()

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
            state.speech_recognition.wake_engines,
        ),
    )
    def handle_speech_recognition(
        self,
        data: tuple[
            SpeechRecognitionStatus,
            Sequence[SpeechRecognitionIntent],
            Sequence[WakeWordEngineConfig],
        ],
        recognition: Recognition,
    ) -> None:
        """Dispatch whatever the armed grammar just matched.

        Whether a matched command runs a voice shortcut or short-circuits a
        quick-chat turn is the reducer's call, from ``status``.
        """
        status, intents, wake_engines = data
        if status is SpeechRecognitionStatus.IDLE:
            return

        action = match_recognition(
            recognition.text,
            intents,
            stop_talking_triggers(wake_engines),
        )
        if action is None:
            return

        logger.info(
            'Speech recognition matched',
            extra={
                'engine_name': recognition.engine_name,
                'text': recognition.text,
                'status': status,
                'action': type(action).__name__,
            },
        )
        store.dispatch(action)

    async def _monitor_wake_engine(self, engine_name: WakeWordEngineName) -> None:
        """Monitor one wake engine's detections and dispatch reports."""
        engine = self._wake_engines[engine_name]
        while True:
            async for trigger_id in engine.wake_word_recogntions():
                await self._handle_wake_detection(engine_name, trigger_id)
            await asyncio.sleep(0.1)

    async def _handle_wake_detection(
        self,
        engine_name: WakeWordEngineName,
        trigger_id: str,
    ) -> None:
        """Resolve a fired trigger, debounce, dump the buffer and report it."""
        entry = self._trigger_index.get(engine_name, {}).get(trigger_id)
        if entry is None:
            return
        value, mode = entry

        # STOP_TALKING must always get through (e.g. a "stop" right after a wake);
        # other modes debounce per-mode so a phrase matching two concurrent engines
        # only fires once without cross-mode suppression.
        if mode is not WakeMode.STOP_TALKING:
            now = asyncio.get_event_loop().time()
            last = self._last_detection_time.get(mode, 0.0)
            if now - last < _DETECTION_DEBOUNCE_SECONDS:
                logger.debug(
                    'Debounced wake detection',
                    extra={
                        'engine_name': engine_name.value,
                        'trigger_id': trigger_id,
                    },
                )
                return
            self._last_detection_time[mode] = now

        if mode is not WakeMode.INTENTS:
            # Persist the rolling mic buffer for the assistant wake/stop phrases.
            # Run the synchronous WAV write off the loop so the dispatch isn't
            # delayed.
            await asyncio.get_event_loop().run_in_executor(
                None,
                self.mic_buffer.dump,
                value,
            )
        store.dispatch(
            SpeechRecognitionReportWakeWordDetectionAction(
                engine_name=engine_name.value,
                trigger_id=trigger_id,
                phrase=value,
            ),
        )

    async def _monitor_speech_recognitions(self) -> None:
        """Monitor speech recognitions and handle them."""
        while True:
            async for recognition in self._speech_engine.speech_recognitions():
                self.handle_speech_recognition(recognition)
            await asyncio.sleep(0.1)

    def _track_monitor_task(self, task: asyncio.Task) -> None:
        """Store the real monitor ``Task`` so ``_cleanup`` can cancel it.

        ``create_task`` only exposes the long-lived task via this callback (its
        return value is the scheduling handle), so capture it here.
        """
        self._monitor_tasks.append(task)

    def _cleanup(self) -> None:
        """Cleanup function to stop all engines (each instance once).

        Vosk is both the speech engine and a wake engine, so de-dupe by instance
        to avoid a double ``stop()`` whose ordering could matter.
        """
        for task in self._monitor_tasks:
            task.cancel()
        for engine in {self._speech_engine, *self._wake_engines.values()}:
            engine.stop()
