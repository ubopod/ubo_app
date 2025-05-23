"""Implement `init_service` for speech recognition service."""

from __future__ import annotations

import asyncio
import io
import json
import wave
from asyncio import Queue, get_event_loop
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Literal

import numpy as np
import soxr
from constants import VOSK_MODEL_PATH
from download_model import download_vosk_model
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadlessMenu, SubMenuItem
from vosk import KaldiRecognizer, Model

from ubo_app.constants import ASSISTANT_END_WORD, ASSISTANT_WAKE_WORD, WAKE_WORD
from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioReportAudioEvent
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionIntent,
    SpeechRecognitionReportIntentDetectionAction,
    SpeechRecognitionReportSpeechAction,
    SpeechRecognitionReportTextEvent,
    SpeechRecognitionReportWakeWordDetectionAction,
    SpeechRecognitionSetIsAssistantActiveAction,
    SpeechRecognitionSetIsIntentsActiveAction,
    SpeechRecognitionState,
    SpeechRecognitionStatus,
)
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.gui import SELECTED_ITEM_PARAMETERS, UNSELECTED_ITEM_PARAMETERS
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.utils.types import Subscriptions

FRAME_RATE = 16_000
SAMPLE_WIDTH = 2


class _Context:
    recognizer: KaldiRecognizer | None = None
    set_word_event = asyncio.Event()
    set_word_lock = asyncio.Lock()

    ongoing_voice: tuple[list[bytes], str] | None

    def __init__(self: _Context) -> None:
        self.ongoing_voice = None
        self.set_word_event.set()

        self.last_chunk_timestamp = 0
        self.chunks_queue = Queue(maxsize=50)

    def set_recognizer(self: _Context, recognizer: KaldiRecognizer) -> None:
        self.recognizer = recognizer

    def unset_recognizer(self: _Context) -> None:
        self.recognizer = None

    def start_recording_ongoing_voice(self: _Context) -> None:
        if self.ongoing_voice is not None:
            msg = 'Recording already started'
            raise ValueError(msg)
        self.ongoing_voice = ([], '')

    def append_to_ongoing_voice(
        self: _Context,
        *,
        text: str | None = None,
        chunk: bytes | None = None,
    ) -> None:
        if self.ongoing_voice is None:
            return
        if text is not None:
            self.ongoing_voice = (
                self.ongoing_voice[0],
                self.ongoing_voice[1] + ' ' + text,
            )
        if chunk is not None:
            self.ongoing_voice = (
                [*self.ongoing_voice[0], chunk],
                self.ongoing_voice[1],
            )

    def end_recording_ongoing_voice(self: _Context) -> None:
        if self.ongoing_voice is None:
            msg = 'Recording not started'
            raise ValueError(msg)
        recorded_voice = self.ongoing_voice
        self.ongoing_voice = None
        audio_buffer = io.BytesIO()
        with wave.open(audio_buffer, 'wb') as wave_file:
            wave_file.setnchannels(1)
            wave_file.setsampwidth(SAMPLE_WIDTH)
            wave_file.setframerate(FRAME_RATE)
            wave_file.writeframes(b''.join(recorded_voice[0]))
        store.dispatch(
            SpeechRecognitionReportSpeechAction(
                text=recorded_voice[1],
                raw_audio=audio_buffer.getvalue(),
            ),
        )

    async def queue_audio_chunk(self, event: AudioReportAudioEvent) -> None:
        if event.timestamp <= self.last_chunk_timestamp or not _is_active():
            return
        self.last_chunk_timestamp = event.timestamp

        if not VOSK_MODEL_PATH.exists():
            store.dispatch(
                SpeechRecognitionSetIsIntentsActiveAction(is_active=False),
                SpeechRecognitionSetIsAssistantActiveAction(is_active=False),
            )
            return

        if event.sample:
            data = event.sample
            data = np.frombuffer(data, dtype=np.int16)
            data = data.reshape(-1, event.channels)
            data = data.T
            data = data.astype(np.float32) / 32768.0

            data = data.squeeze() if event.channels == 1 else np.mean(data, axis=0)

            if event.rate != FRAME_RATE:
                data = soxr.resample(
                    data,
                    in_rate=event.rate,
                    out_rate=FRAME_RATE,
                )

            data = (data * 32768.0).astype(np.int16).tobytes()

            await self.chunks_queue.put(data)


_context = _Context()


@store.with_state(
    lambda state: (
        state.speech_recognition.is_intents_active,
        state.speech_recognition.is_assistant_active,
    ),
)
def _is_active(data: tuple[bool, bool]) -> bool:
    return any(data)


@store.with_state(lambda state: state.speech_recognition)
def _phrases(state: SpeechRecognitionState) -> list[str]:
    if state.status == SpeechRecognitionStatus.IDLE:
        items = []
        if state.is_intents_active:
            items.append(WAKE_WORD)
        if state.is_assistant_active:
            items.append(ASSISTANT_WAKE_WORD)
        return [*items, '[unk]']
    if state.status == SpeechRecognitionStatus.INTENTS_WAITING:
        return [
            phrase.lower()
            for intent in state.intents
            for phrase in (
                [intent.phrase] if isinstance(intent.phrase, str) else intent.phrase
            )
        ] + ['[unk]']
    if state.status == SpeechRecognitionStatus.ASSISTANT_WAITING:
        return []

    msg = 'Invalid status for speech recognition service'
    raise ValueError(msg)


@store.autorun(
    lambda state: state.speech_recognition,
    options=AutorunOptions(initial_call=False),
)
async def _update_intents(state: SpeechRecognitionState) -> None:
    if not _context.recognizer:
        return

    phrases = _phrases()

    logger.debug(
        'Vosk - Setting phrases',
        extra={
            'status': state.status,
            'phrases': phrases,
            'wake_word': WAKE_WORD,
            'assistant_wake_word': ASSISTANT_WAKE_WORD,
            'assistant_end_word': ASSISTANT_END_WORD,
        },
    )
    async with _context.set_word_lock:
        _context.set_word_event.clear()
        await _context.set_word_event.wait()
        _context.recognizer.SetGrammar(json.dumps(phrases))


@store.with_state(
    lambda state: (
        state.speech_recognition.intents,
        state.speech_recognition.status,
    ),
)
def _handle_result(
    data: tuple[Sequence[SpeechRecognitionIntent], SpeechRecognitionStatus],
    *,
    result: dict[Literal['text'], str],
) -> None:
    intents, status = data

    if 'text' not in result or not result['text']:
        return

    logger.info(
        'Vosk - Text recognized',
        extra={
            'result': result,
            'status': status,
        },
    )
    logger.debug(
        'Vosk - Text recognized',
        extra={
            'result': result,
            'status': status,
            'phrases': _phrases(),
            'intents': intents,
            'wake_word': WAKE_WORD,
            'assistant_wake_word': ASSISTANT_WAKE_WORD,
            'assistant_end_word': ASSISTANT_END_WORD,
        },
    )

    text = result['text']

    if status == SpeechRecognitionStatus.IDLE:
        if text == WAKE_WORD:
            store.dispatch(
                SpeechRecognitionReportWakeWordDetectionAction(
                    wake_word=WAKE_WORD,
                ),
            )
            logger.info('Vosk - Wake word recognized')
        elif text == ASSISTANT_WAKE_WORD:
            store.dispatch(
                SpeechRecognitionReportWakeWordDetectionAction(
                    wake_word=ASSISTANT_WAKE_WORD,
                ),
            )
            logger.info('Vosk - AI wake word recognized')
            _context.start_recording_ongoing_voice()

    elif status == SpeechRecognitionStatus.INTENTS_WAITING:
        if intent := next(
            (
                intent
                for intent in intents
                if (
                    intent.phrase.lower() == text.lower()
                    if isinstance(intent.phrase, str)
                    else text.lower() in [phrase.lower() for phrase in intent.phrase]
                )
            ),
            None,
        ):
            logger.info('Vosk - Phrase recognized')
            store.dispatch(
                SpeechRecognitionReportIntentDetectionAction(intent=intent),
            )
    elif status == SpeechRecognitionStatus.ASSISTANT_WAITING:
        indices = [
            text.index(term) for term in ASSISTANT_END_WORD.split() if term in text
        ]
        if len(indices) == len(ASSISTANT_END_WORD.split()) and indices == sorted(
            indices,
        ):
            _context.end_recording_ongoing_voice()
            logger.info('Vosk - AI end word recognized')
        else:
            _context.append_to_ongoing_voice(text=result['text'])


@store.with_state(lambda state: state.speech_recognition.intents)
async def _run_listener_thread(
    _data: Sequence[SpeechRecognitionIntent],
) -> None:
    intents = _data

    if not VOSK_MODEL_PATH.exists():
        store.dispatch(SpeechRecognitionSetIsIntentsActiveAction(is_active=False))
        return

    logger.debug(
        'Vosk - Initializing model',
        extra={
            'intents': intents,
            'phrases': _phrases(),
        },
    )
    model = Model(
        model_path=VOSK_MODEL_PATH.resolve().as_posix(),
        lang='en-us',
    )
    _context.set_recognizer(KaldiRecognizer(model, FRAME_RATE, json.dumps(_phrases())))

    process_executor = ThreadPoolExecutor(max_workers=1)

    logger.debug('Vosk - Listening for commands...')

    while _is_active() and _context.recognizer:
        data = await _context.chunks_queue.get()

        if result := await get_event_loop().run_in_executor(
            process_executor,
            _context.recognizer.AcceptWaveform,
            data,
        ):
            result = json.loads(_context.recognizer.Result())

            _handle_result(result=result)
        else:
            result = json.loads(_context.recognizer.PartialResult())
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

        _context.append_to_ongoing_voice(chunk=data)

        # This is to make sure recognizer does not run when its grammar is being set
        if not _context.set_word_event.is_set():
            _context.recognizer.Reset()
            _context.set_word_event.set()
            async with _context.set_word_lock:
                ...


@store.autorun(
    lambda state: (
        state.speech_recognition.is_intents_active,
        state.speech_recognition.is_assistant_active,
    ),
)
def _vosk_items(data: tuple[bool, bool]) -> list[ActionItem]:
    is_intents_active, is_assistant_active = data

    if not VOSK_MODEL_PATH.exists():
        return [
            ActionItem(
                key='download',
                label='Download Vosk Model',
                icon='󰇚',
                action=download_vosk_model,
            ),
        ]

    return [
        UboDispatchItem(
            key='is_intents_active',
            label='Command Interface',
            store_action=SpeechRecognitionSetIsIntentsActiveAction(
                is_active=not is_intents_active,
            ),
            **(
                SELECTED_ITEM_PARAMETERS
                if is_intents_active
                else UNSELECTED_ITEM_PARAMETERS
            ),
        ),
        UboDispatchItem(
            key='is_assistant_active',
            label='Voice Assistant',
            store_action=SpeechRecognitionSetIsAssistantActiveAction(
                is_active=not is_assistant_active,
            ),
            **(
                SELECTED_ITEM_PARAMETERS
                if is_assistant_active
                else UNSELECTED_ITEM_PARAMETERS
            ),
        ),
    ]


def init_service() -> Subscriptions:
    """Initialize speech recognition service."""

    @store.autorun(
        lambda state: state.speech_recognition.is_intents_active
        or state.speech_recognition.is_assistant_active,
    )
    async def run_listener(is_active: bool) -> None:  # noqa: FBT001
        if is_active:
            await _run_listener_thread()

    register_persistent_store(
        'speech_recognition:is_intents_active',
        lambda state: state.speech_recognition.is_intents_active,
    )
    register_persistent_store(
        'speech_recognition:is_assistant_active',
        lambda state: state.speech_recognition.is_assistant_active,
    )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.SPEECH,
            priority=1,
            menu_item=SubMenuItem(
                label='Speech Recognition',
                icon='󰗋',
                sub_menu=HeadlessMenu(
                    title='󰗋Speech Recognition',
                    items=_vosk_items,
                ),
            ),
        ),
    )

    return [
        _context.unset_recognizer,
        store.subscribe_event(AudioReportAudioEvent, _context.queue_audio_chunk),
    ]
