"""Implement `init_service` for speech recognition service."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from constants import VOSK_MODEL_PATH
from download_model import download_vosk_model
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadlessMenu, SubMenuItem
from vosk import KaldiRecognizer, Model

from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.dispatch_action import DispatchItem
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionSetIsActiveAction,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import to_thread
from ubo_app.utils.gui import SELECTED_ITEM_PARAMETERS, UNSELECTED_ITEM_PARAMETERS
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions

SAMPLE_RATE = 16_000
BUFFER_SIZE = 4_000


class _Context:
    recognizer: KaldiRecognizer | None = None

    def set_recognizer(self: _Context, recognizer: KaldiRecognizer) -> None:
        self.recognizer = recognizer

    def unset_recognizer(self: _Context) -> None:
        self.recognizer = None


_context = _Context()


@store.with_state(lambda state: state.speech_recognition.is_active)
def _is_active(is_active: bool) -> bool:  # noqa: FBT001
    return is_active


def _run_listener_thread() -> None:
    if not VOSK_MODEL_PATH.exists():
        store.dispatch(SpeechRecognitionSetIsActiveAction(is_active=False))
        return

    logger.debug('Vosk - Initializing model')
    model = Model(
        model_path=VOSK_MODEL_PATH.resolve().as_posix(),
        lang='en-us',
    )
    _context.set_recognizer(
        KaldiRecognizer(model, SAMPLE_RATE),
    )
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
        read_function = input_audio.read
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

        def read_function() -> tuple[int, bytes]:
            data = stream.read(BUFFER_SIZE, exception_on_overflow=False)
            return len(data), data

    logger.debug('Vosk - Listening for commands...')
    while _is_active() and _context.recognizer:
        length, data = read_function()
        if length > 0 and _context.recognizer.AcceptWaveform(data):
            result = json.loads(_context.recognizer.Result())['text']
            logger.debug('Vosk', extra={'result': result})


@store.autorun(
    lambda state: state.speech_recognition.is_active,
    options=AutorunOptions(memoization=False),
)
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
    def run_listener(is_active: bool) -> None:  # noqa: FBT001
        if is_active:
            to_thread(_run_listener_thread)

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
