"""Implement `init_service` for speech recognition service."""

from __future__ import annotations

import json
import threading
from asyncio import get_event_loop
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Literal

from constants import VOSK_MODEL_PATH
from download_model import download_vosk_model
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadlessMenu, SubMenuItem
from vosk import KaldiRecognizer, Model

from ubo_app.constants import WAKE_WORD
from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.dispatch_action import DispatchItem
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionIntent,
    SpeechRecognitionReportIntentDetectionAction,
    SpeechRecognitionReportWakeWordDetectionAction,
    SpeechRecognitionSetIsActiveAction,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.gui import SELECTED_ITEM_PARAMETERS, UNSELECTED_ITEM_PARAMETERS
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.utils.types import Subscriptions

SAMPLE_RATE = 16_000
BUFFER_SIZE = 4_000


class _Context:
    recognizer: KaldiRecognizer | None = None
    set_word_event = threading.Event()
    set_word_lock = threading.Lock()

    def set_recognizer(self: _Context, recognizer: KaldiRecognizer) -> None:
        self.recognizer = recognizer

    def unset_recognizer(self: _Context) -> None:
        self.recognizer = None


_context = _Context()


@store.with_state(lambda state: state.speech_recognition.is_active)
def _is_active(is_active: bool) -> bool:  # noqa: FBT001
    return is_active


@store.view(lambda state: state.speech_recognition.intents)
def _phrases(intents: Sequence[SpeechRecognitionIntent]) -> list[str]:
    return [
        phrase.lower()
        for intent in intents
        for phrase in (
            [intent.phrase] if isinstance(intent.phrase, str) else intent.phrase
        )
    ]


@store.autorun(
    lambda state: (state.speech_recognition.is_waiting),
    options=AutorunOptions(initial_call=False, memoization=False),
)
def _update_intents(is_waiting: bool) -> None:  # noqa: FBT001
    if not _context.recognizer:
        return

    logger.debug(
        'Vosk - Setting phrases',
        extra={
            'is_waiting': is_waiting,
            'phrases': _phrases(),
            'wake_word': WAKE_WORD,
        },
    )
    with _context.set_word_lock:
        _context.set_word_event.clear()
        _context.set_word_event.wait()
        _context.recognizer.SetGrammar(
            json.dumps([*_phrases(), '[unk]'] if is_waiting else [WAKE_WORD, '[unk]']),
        )


@store.with_state(
    lambda state: (
        state.speech_recognition.intents,
        state.speech_recognition.is_waiting,
    ),
)
def _handle_result(
    data: tuple[Sequence[SpeechRecognitionIntent], bool],
    result: dict[Literal['text'], str],
) -> None:
    intents, is_waiting = data
    if 'text' not in result or not result['text']:
        return
    logger.debug(
        'Vosk - Text recognized',
        extra={
            'is_waiting': is_waiting,
            'result': result,
            'intents': intents,
            'wake_word': WAKE_WORD,
        },
    )

    text = result['text']

    if is_waiting:
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
    elif text == WAKE_WORD:
        store.dispatch(SpeechRecognitionReportWakeWordDetectionAction())
        logger.info('Vosk - Wake word recognized')


@store.with_state(
    lambda state: (
        state.speech_recognition.intents,
        state.speech_recognition.is_waiting,
    ),
)
async def _run_listener_thread(
    _data: tuple[Sequence[SpeechRecognitionIntent], bool],
) -> None:
    intents, is_waiting = _data

    if not VOSK_MODEL_PATH.exists():
        store.dispatch(SpeechRecognitionSetIsActiveAction(is_active=False))
        return

    logger.debug(
        'Vosk - Initializing model',
        extra={'intents': intents if is_waiting else [WAKE_WORD]},
    )
    model = Model(
        model_path=VOSK_MODEL_PATH.resolve().as_posix(),
        lang='en-us',
    )
    _context.set_recognizer(
        KaldiRecognizer(
            model,
            SAMPLE_RATE,
            json.dumps([*_phrases(), '[unk]'] if is_waiting else [WAKE_WORD, '[unk]']),
        ),
    )

    executor = ThreadPoolExecutor()

    if IS_RPI:
        import alsaaudio  # type: ignore [reportMissingModuleSource=false]

        input_audio = alsaaudio.PCM(
            alsaaudio.PCM_CAPTURE,
            alsaaudio.PCM_NORMAL,
            channels=1,
            rate=SAMPLE_RATE,
            format=alsaaudio.PCM_FORMAT_S16_LE,
            periodsize=BUFFER_SIZE,
        )

        async def read_audio_chunk() -> tuple[int, bytes]:
            return await get_event_loop().run_in_executor(
                executor,
                input_audio.read,
            )
    else:
        import pyaudio

        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=BUFFER_SIZE,
        )

        async def read_audio_chunk() -> tuple[int, bytes]:
            data = await get_event_loop().run_in_executor(
                executor,
                stream.read,
                BUFFER_SIZE,
                False,  # noqa: FBT003
            )
            return len(data), data

    logger.debug('Vosk - Listening for commands...')
    _context.set_word_event.set()
    while _is_active() and _context.recognizer:
        length, data = await read_audio_chunk()
        if length > 0 and await get_event_loop().run_in_executor(
            executor,
            _context.recognizer.AcceptWaveform,
            data,
        ):
            result = json.loads(_context.recognizer.FinalResult())

            _handle_result(result)

        if not _context.set_word_event.is_set():
            _context.recognizer.Reset()
            _context.set_word_event.set()
            with _context.set_word_lock:
                ...


@store.autorun(lambda state: state.speech_recognition.is_active)
def _vosk_items(is_active: bool) -> list[ActionItem]:  # noqa: FBT001
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
        DispatchItem(
            key='is_active',
            label='Is Active',
            store_action=SpeechRecognitionSetIsActiveAction(
                is_active=not is_active,
            ),
            **(SELECTED_ITEM_PARAMETERS if is_active else UNSELECTED_ITEM_PARAMETERS),
        ),
    ]


def init_service() -> Subscriptions:
    """Initialize speech recognition service."""

    @store.autorun(lambda state: state.speech_recognition.is_active)
    async def run_listener(is_active: bool) -> None:  # noqa: FBT001
        if is_active:
            await _run_listener_thread()

    register_persistent_store(
        'speech_recognition:is_active',
        lambda state: state.speech_recognition.is_active,
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

    return [_context.unset_recognizer]
