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


class _RecognizerState(NamedTuple):
    """The loaded Vosk model/recognizer and what they were built for."""

    model: Model | None
    recognizer: KaldiRecognizer | None
    model_id: str | None
    phrases: tuple[str, ...] | None


def _load_model(model_id: str) -> Model | None:
    """Load the Vosk model if it's on disk, else None (not downloaded yet)."""
    from vosk import Model

    model_dir = Path(str(model_path_for(model_id)))
    if not model_dir.exists():
        return None
    return Model(model_path=model_dir.resolve().as_posix())


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

        super().__init__(label='Vosk')

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

            if requested_model_id != state.model_id or recognizer is None:
                model_changed = requested_model_id != state.model_id
                new_model = _load_model(requested_model_id)
                if new_model is not None:
                    logger.debug(
                        'Vosk - Loaded model',
                        extra={'model_id': requested_model_id},
                    )
                    return _RecognizerState(
                        new_model,
                        _make_recognizer(new_model, phrases),
                        requested_model_id,
                        phrases,
                    )
                if recognizer is not None:
                    # Switched to a not-yet-downloaded model; keep the working
                    # one rather than going silent.
                    logger.warning(
                        'Vosk - Requested model not on disk, staying on '
                        'previous model',
                        extra={'model_id': requested_model_id},
                    )
                elif model_changed:
                    logger.debug(
                        'Vosk - Selected model not on disk yet; waiting for '
                        'download',
                        extra={'model_id': requested_model_id},
                    )
                return state._replace(model_id=requested_model_id)

            if phrases != state.phrases and model is not None:
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
            model_id=None,
            phrases=None,
        )

        while self.should_be_running():
            data = await self.input_queue.get()

            state = await self._reconcile(state)
            recognizer = state.recognizer
            if recognizer is None:
                continue

            if await get_event_loop().run_in_executor(
                self.process_executor,
                recognizer.AcceptWaveform,
                data,
            ):
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
