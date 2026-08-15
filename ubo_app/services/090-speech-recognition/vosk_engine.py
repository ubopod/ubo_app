"""Vosk speech recognition engine."""

from __future__ import annotations

import asyncio
import json
from asyncio import get_event_loop
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from abstraction.speech_recognition_mixin import (
    PhraseRecognition,
    SpeechRecognition,
    SpeechRecognitionMixin,
)
from abstraction.wake_word_recognition_mixin import WakeWordRecognitionMixin
from typing_extensions import override

from ubo_app.constants import SPEECH_RECOGNITION_FRAME_RATE
from ubo_app.engines.vosk import VoskEngine as BaseVosk
from ubo_app.engines.vosk_catalog import DEFAULT_VOSK_MODEL_ID, model_path_for
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionReportTextEvent,
)
from ubo_app.utils import IS_RPI

if TYPE_CHECKING:
    from vosk import KaldiRecognizer, Model


@store.with_state(lambda state: state.assistant.selected_vosk_model)
def _read_selected_model(selected_model: str) -> str:
    return selected_model or DEFAULT_VOSK_MODEL_ID


# Minimum gap between attempts to (re)load a not-yet-ready model. ``_run``
# reconciles before every ~50ms mic chunk; without this throttle a model that
# is missing or mid-extraction would be retried (and logged) ~20 times/second.
_MODEL_RETRY_INTERVAL_SECONDS = 1.0


class _RecognizerState(NamedTuple):
    """The loaded Vosk model/recognizer and what they were built for."""

    model: Model | None
    recognizer: KaldiRecognizer | None
    # The model id actually loaded into ``recognizer``. Only advances on a
    # successful load, so a selected-but-not-ready model keeps being retried
    # instead of being abandoned while the previous recognizer lingers.
    loaded_model_id: str | None
    phrases: tuple[str, ...] | None
    # Loop time before which a failed (re)load must not be re-attempted.
    retry_at: float


def _load_model(model_id: str) -> Model | None:
    """Load the Vosk model if it's on disk and valid, else None (retry later).

    Returns None — never raises — when the model isn't ready: the directory may
    not exist yet, or it may exist but be mid-extraction (``Model()`` then
    raises "Failed to create a model"). The caller keeps the engine alive and
    retries on the next audio chunk, so a just-downloaded model loads cleanly
    once extraction finishes instead of crashing the recognition loop.
    """
    from vosk import Model

    model_dir = Path(str(model_path_for(model_id)))
    if not model_dir.exists():
        return None
    try:
        return Model(model_path=model_dir.resolve().as_posix())
    except Exception as exception:  # noqa: BLE001
        logger.warning(
            'Vosk - Could not load model yet (incomplete download?); will retry',
            extra={'model_id': model_id, 'error': str(exception)},
        )
        return None


def _make_recognizer(
    model: Model,
    phrases: tuple[str, ...] | None,
) -> KaldiRecognizer:
    """Build a recognizer for *model*, limited to *phrases* when provided."""
    from vosk import KaldiRecognizer

    return KaldiRecognizer(
        model,
        SPEECH_RECOGNITION_FRAME_RATE,
        *([json.dumps(phrases)] if phrases else []),
    )


class VoskEngine(
    BaseVosk,
    SpeechRecognitionMixin,
    WakeWordRecognitionMixin,
):
    """Vosk speech recognition engine."""

    def __init__(self) -> None:
        """Initialize Vosk speech recognition engine."""
        self.grammar_lock = asyncio.Lock()
        self.process_executor = ThreadPoolExecutor(max_workers=1)
        # The single loaded model instance, cached for vocabulary validation
        # (wake-phrase editing). None until ``_reconcile`` first loads a model;
        # never a second ``Model`` — this is the same instance the recognizer uses.
        self._loaded_model: Model | None = None

        super().__init__(label='Vosk')

    def current_model(self) -> Model | None:
        """Return the loaded Vosk model, or None if not loaded yet.

        Used by the wake-phrase editor to validate words against the Kaldi
        vocabulary (``model.vosk_model_find_word``). Best-effort: a plain
        reference read of the one model the recognition loop already holds.
        """
        return self._loaded_model

    @override
    def _checked_run(self) -> bool:
        """Run the wake-word engine even when the model isn't downloaded yet.

        The base ``NeedsSetupMixin._checked_run`` blocks the engine (returns
        without starting ``_run``) while ``is_setup`` is False, and only the
        download flow's ``decide_running_state`` ever restarts it — a fragile
        path that leaves recognition dead until an app restart. That gate is a
        regression from unifying this engine with the assistant's NeedsSetup
        lifecycle (commit b0fb29f3, v1.7); before it, the speech-recognition
        Vosk engine ran its own lifecycle and started at boot.

        Unlike credential-based engines, the Vosk wake-word engine is safe to
        run without its model: ``_run``/``_reconcile`` keep the loop alive,
        drop audio while the model is missing, and load it the moment it's
        downloaded — so the engine started at boot self-heals on the next audio
        chunk with no restart.
        """
        return self._original_run()

    async def _reconcile(self, state: _RecognizerState) -> _RecognizerState:
        """Reconcile the recognizer with the selected model and phrases.

        The model is loaded lazily: while the selected model isn't on disk yet
        (first-time setup, download in progress) the returned state carries
        ``recognizer=None`` and ``_run`` drops audio. The recognizer is built
        the moment the model appears on disk, so a model downloaded at runtime
        self-heals on the next chunk — no app restart, unlike an eager load that
        would crash the engine at boot when the model is still missing.
        """
        async with self.grammar_lock:
            requested_model_id = _read_selected_model()
            phrases = self._phrases
            model = state.model
            recognizer = state.recognizer

            if requested_model_id != state.loaded_model_id:
                # The selection differs from what's loaded (changed, or never
                # loaded). Attempt a load, but no more than once per
                # ``_MODEL_RETRY_INTERVAL_SECONDS`` so a missing / mid-extraction
                # model doesn't get hammered (and logged) on every mic chunk.
                now = get_event_loop().time()
                if now < state.retry_at:
                    return state
                new_model = _load_model(requested_model_id)
                if new_model is not None:
                    logger.debug(
                        'Vosk - Loaded model',
                        extra={'model_id': requested_model_id},
                    )
                    # Cache the one model instance for wake-phrase validation
                    # (under ``grammar_lock``); never a second ``Model``.
                    self._loaded_model = new_model
                    # ``loaded_model_id`` advances only here, on success.
                    return _RecognizerState(
                        new_model,
                        _make_recognizer(new_model, phrases),
                        requested_model_id,
                        phrases,
                        0.0,
                    )
                # Not ready yet. Keep the current recognizer (if any) and the
                # current ``loaded_model_id`` so the requested model is retried;
                # back off until the next interval.
                if recognizer is not None:
                    logger.warning(
                        'Vosk - Requested model not ready; staying on previous '
                        'model',
                        extra={'model_id': requested_model_id},
                    )
                else:
                    logger.debug(
                        'Vosk - Selected model not ready; waiting',
                        extra={'model_id': requested_model_id},
                    )
                return state._replace(
                    retry_at=now + _MODEL_RETRY_INTERVAL_SECONDS,
                )

            if (
                phrases != state.phrases
                and model is not None
                and recognizer is not None
            ):
                logger.debug('Vosk - Updating phrases', extra={'new_phrases': phrases})
                if IS_RPI:
                    recognizer.Reset()
                    recognizer.SetGrammar(json.dumps(phrases))
                    return state._replace(phrases=phrases)
                return state._replace(
                    recognizer=_make_recognizer(model, phrases),
                    phrases=phrases,
                )

            return state

    @override
    async def _run(self) -> None:
        # The model is loaded lazily and reconciled before each chunk (see
        # ``_reconcile``): on first-time setup the selected model isn't on disk
        # yet (the core downloads it on demand). An eager load here would crash
        # the engine at boot, and nothing reliably restarts it once the download
        # finishes, leaving recognition dead until an app restart. Instead the
        # loop stays alive with no recognizer, drops audio while the model is
        # missing, and builds the recognizer the moment it appears — so a model
        # downloaded at runtime self-heals on the next audio chunk.
        logger.debug(
            'Vosk - Starting recognition loop',
            extra={'engine_name': self.name},
        )
        state = _RecognizerState(
            model=None,
            recognizer=None,
            loaded_model_id=None,
            phrases=None,
            retry_at=0.0,
        )

        while self.should_be_running():
            data = await self.input_queue.get()

            state = await self._reconcile(state)
            recognizer = state.recognizer
            if recognizer is None:
                continue

            try:
                accepted = await get_event_loop().run_in_executor(
                    self.process_executor,
                    recognizer.AcceptWaveform,
                    data,
                )
            except TypeError:
                # A malformed chunk must not kill this loop: nothing else
                # restarts it (``decide_running_state`` only re-fires on a
                # trigger-config change), so one bad chunk would otherwise
                # silently and permanently stop speech recognition.
                logger.warning(
                    'Vosk - Dropping malformed audio chunk',
                    extra={'chunk_type': type(data).__name__},
                )
                continue

            if accepted:
                result = json.loads(recognizer.FinalResult())
                if result.get('text'):
                    await self.report(result=result['text'])
            else:
                result = json.loads(recognizer.PartialResult())
                if result.get('partial'):
                    logger.verbose(
                        'Vosk - Partial result',
                        extra={'result': result},
                    )
                    store._dispatch(  # noqa: SLF001
                        [
                            SpeechRecognitionReportTextEvent(
                                timestamp=get_event_loop().time(),
                                text=result['partial'],
                            ),
                        ],
                    )

            if self.ongoing_recognition is not None:
                self.ongoing_recognition.append_voice(data)

    @property
    def _phrases(self) -> tuple[str, ...] | None:
        """Get the phrases for the Vosk recognizer."""
        if self.ongoing_recognition:
            if isinstance(self.ongoing_recognition, SpeechRecognition):
                return ()
            if isinstance(self.ongoing_recognition, PhraseRecognition):
                return (
                    *self.ongoing_recognition.phrases,
                    '[unk]',
                )
            msg = 'Ongoing recognition must have either end_phrase or phrases set.'
            raise ValueError(msg)

        if self.wake_words:
            return (*self.wake_words, '[unk]')

        return None
