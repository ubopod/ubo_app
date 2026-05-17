"""Vosk speech recognition engine."""

from __future__ import annotations

import asyncio
import json
from asyncio import get_event_loop
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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


@store.with_state(lambda state: state.assistant.selected_vosk_model)
def _read_selected_model(selected_model: str) -> str:
    return selected_model or DEFAULT_VOSK_MODEL_ID


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

    @override
    async def _run(self) -> None:
        from vosk import KaldiRecognizer, Model

        phrases = self._phrases
        current_model_id = _read_selected_model()
        model_dir = Path(str(model_path_for(current_model_id)))
        model = Model(
            model_path=model_dir.resolve().as_posix(),
        )
        logger.debug(
            'Vosk - Starting recognition loop',
            extra={
                'engine_name': self.name,
                'phrases': phrases,
                'model_id': current_model_id,
            },
        )
        recognizer = KaldiRecognizer(
            model,
            SPEECH_RECOGNITION_FRAME_RATE,
            *([json.dumps(phrases)] if phrases else []),
        )

        while self.should_be_running():
            data = await self.input_queue.get()

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

            async with self.grammar_lock:
                requested_model_id = _read_selected_model()
                if requested_model_id != current_model_id:
                    logger.debug(
                        'Vosk - Switching model',
                        extra={
                            'old_model_id': current_model_id,
                            'new_model_id': requested_model_id,
                        },
                    )
                    current_model_id = requested_model_id
                    model_dir = Path(str(model_path_for(current_model_id)))
                    if not model_dir.exists():
                        logger.warning(
                            'Vosk - Requested model not on disk, staying on '
                            'previous model',
                            extra={'model_id': current_model_id},
                        )
                    else:
                        model = Model(model_path=model_dir.resolve().as_posix())
                        recognizer = KaldiRecognizer(
                            model,
                            SPEECH_RECOGNITION_FRAME_RATE,
                            *([json.dumps(phrases)] if phrases else []),
                        )
                        continue

                if (_phrases := self._phrases) != phrases:
                    phrases = _phrases
                    logger.debug(
                        'Vosk - Updating phrases',
                        extra={
                            'new_phrases': phrases,
                        },
                    )
                    if IS_RPI:
                        recognizer.Reset()
                        recognizer.SetGrammar(json.dumps(phrases))
                    else:
                        recognizer = KaldiRecognizer(
                            model,
                            SPEECH_RECOGNITION_FRAME_RATE,
                            *([json.dumps(phrases)] if phrases else []),
                        )

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
