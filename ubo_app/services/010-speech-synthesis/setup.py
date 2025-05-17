"""Implement `init_service` for speech synthesis service."""

from __future__ import annotations

import functools
import hashlib
import json
import struct
from asyncio import CancelledError
from queue import Queue
from typing import TYPE_CHECKING

import fasteners
import pvorca
from constants import PIPER_MODEL_HASH, PIPER_MODEL_JSON_PATH, PIPER_MODEL_PATH
from download_model import download_piper_model
from piper.voice import PiperVoice  # pyright: ignore [reportMissingModuleSource]
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, SubMenuItem

from ubo_app.constants import PICOVOICE_ACCESS_KEY
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.input.types import InputFieldDescription, InputFieldType
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioPlayAudioAction, AudioPlaybackDoneEvent
from ubo_app.store.services.speech_synthesis import (
    ReadableInformation,
    SpeechSynthesisEngine,
    SpeechSynthesisReadTextAction,
    SpeechSynthesisSetEngineAction,
    SpeechSynthesisSynthesizeTextEvent,
    SpeechSynthesisUpdateAccessKeyStatus,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task, to_thread
from ubo_app.utils.gui import SELECTED_ITEM_PARAMETERS, UNSELECTED_ITEM_PARAMETERS
from ubo_app.utils.input import ubo_input
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_app.utils.types import Subscriptions


class _Context:
    picovoice_instance: pvorca.Orca | None = None
    piper_voice: PiperVoice | None = None
    picovoice_lock = fasteners.ReaderWriterLock()

    def cleanup(self: _Context) -> None:
        store.dispatch(SpeechSynthesisUpdateAccessKeyStatus(is_access_key_set=False))
        with self.picovoice_lock.write_lock():
            if self.picovoice_instance:
                self.picovoice_instance.delete()
                self.picovoice_instance = None

    def set_access_key(self: _Context, access_key: str) -> None:
        store.dispatch(SpeechSynthesisUpdateAccessKeyStatus(is_access_key_set=True))
        with self.picovoice_lock.write_lock():
            if access_key:
                if self.picovoice_instance:
                    self.picovoice_instance.delete()
                self.picovoice_instance = pvorca.create(access_key)

    def load_piper(self: _Context) -> None:
        if _is_piper_downloaded():
            self.piper_voice = PiperVoice.load(PIPER_MODEL_PATH)


_context = _Context()


def input_access_key() -> None:
    """Input the Picovoice access key."""

    async def act() -> None:
        try:
            input_result = (
                await ubo_input(
                    title='Picovoice Access Key',
                    qr_code_generation_instructions=ReadableInformation(
                        text='Convert the Picovoice access key to a QR code and hold '
                        'it in front of the camera to scan it.',
                        picovoice_text='Convert the Picovoice access key to a '
                        '{QR|K Y UW AA R} and hold it in front of the camera to scan '
                        'it.',
                    ),
                    prompt='Enter Picovoice Access Key',
                    pattern=r'^(?P<access_key>.*)$',
                    fields=[
                        InputFieldDescription(
                            name='access_key',
                            label='Access Key',
                            description='Enter Picovoice Access Key',
                            type=InputFieldType.TEXT,
                            required=True,
                            title='Picovoice Access Key',
                        ),
                    ],
                )
            )[1]
            access_key = input_result.data.get('access_key')
            if not access_key:
                return
            secrets.write_secret(key=PICOVOICE_ACCESS_KEY, value=access_key)
            to_thread(_context.set_access_key, access_key)
        except CancelledError:
            pass

    create_task(act())


def clear_access_key() -> None:
    """Clear the Picovoice access key."""
    secrets.clear_secret(PICOVOICE_ACCESS_KEY)
    to_thread(_context.cleanup)


@store.with_state(lambda state: state.speech_synthesis.selected_engine)
def _engine(engine: SpeechSynthesisEngine) -> SpeechSynthesisEngine:
    return engine


piper_cache: dict[str, list[bytes]] = {}


def synthesize_and_play(event: SpeechSynthesisSynthesizeTextEvent) -> None:
    """Synthesize the text."""
    engine = _engine()
    if engine == SpeechSynthesisEngine.PIPER:
        text = event.information.piper_text
        if not _context.piper_voice:
            return
        id = hex(hash(text))
        queue = Queue(maxsize=1)

        if text in piper_cache:
            source = piper_cache[text]
            is_first_time = False
        else:
            source = _context.piper_voice.synthesize_stream_raw(text)
            piper_cache[text] = []
            is_first_time = True

        unsubscribe = store.subscribe_event(
            AudioPlaybackDoneEvent,
            lambda event: event.id == id and queue.get(),
        )

        for sample in source:
            if is_first_time:
                piper_cache[text].append(sample)
            queue.put(None)
            store.dispatch(
                AudioPlayAudioAction(
                    id=id,
                    sample=sample,
                    channels=1,
                    rate=22050,
                    width=2,
                ),
            )
        unsubscribe()
    elif engine == SpeechSynthesisEngine.PICOVOICE:
        with _context.picovoice_lock.read_lock():
            if not _context.picovoice_instance:
                return
            rate = _context.picovoice_instance.sample_rate

            audio_sequence = _context.picovoice_instance.synthesize(
                text=event.information.picovoice_text,
                speech_rate=event.speech_rate,
            )
        sample = b''.join(struct.pack('h', sample) for sample in audio_sequence[0])
        store.dispatch(
            AudioPlayAudioAction(
                sample=sample,
                channels=1,
                rate=rate,
                width=2,
            ),
        )


@store.autorun(lambda state: state.speech_synthesis.is_access_key_set)
def _menu_items(is_access_key_set: bool | None) -> Sequence[ActionItem]:
    if is_access_key_set:
        return [
            ActionItem(
                label='Clear Access Key',
                icon='󰌊',
                action=clear_access_key,
            ),
        ]
    return [
        ActionItem(
            label='Set Access Key',
            icon='󰐲',
            action=input_access_key,
        ),
    ]


@store.autorun(lambda state: state.speech_synthesis.is_access_key_set)
def _menu_sub_heading(_: bool | None) -> str:
    return f"""Set the access key
Current value: {secrets.read_covered_secret(PICOVOICE_ACCESS_KEY)}"""


ENGINE_LABELS = {
    SpeechSynthesisEngine.PIPER: 'Piper',
    SpeechSynthesisEngine.PICOVOICE: 'Picovoice',
}


def create_engine_selector(engine: SpeechSynthesisEngine) -> Callable[[], None]:
    """Select the speech synthesis engine."""

    def _engine_selector() -> None:
        store.dispatch(
            SpeechSynthesisSetEngineAction(engine=engine),
            SpeechSynthesisReadTextAction(
                information=ReadableInformation(
                    text={
                        SpeechSynthesisEngine.PIPER: 'Piper speech synthesis engine '
                        'selected',
                        SpeechSynthesisEngine.PICOVOICE: 'Picovoice speech synthesis '
                        'engine selected',
                    }[engine],
                ),
                engine=engine,
            ),
        )

    return _engine_selector


def _download_model_callback() -> None:
    _speech_synthesis_menu()
    _context.load_piper()


def _is_piper_downloaded() -> bool:
    if not PIPER_MODEL_PATH.exists() or not PIPER_MODEL_JSON_PATH.exists():
        return False

    with PIPER_MODEL_JSON_PATH.open('r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return False
        else:
            if data['dataset'] != 'kristin':
                return False

    # check checksum
    with PIPER_MODEL_PATH.open('rb') as f:
        sha256_hash = hashlib.sha256()

        for chunk in iter(lambda: f.read(4096), b''):
            sha256_hash.update(chunk)

        if sha256_hash.hexdigest() != PIPER_MODEL_HASH:
            return False

    return True


@store.autorun(
    lambda state: state.speech_synthesis.selected_engine,
    options=AutorunOptions(memoization=False),
)
def _speech_synthesis_menu(selected_engine: SpeechSynthesisEngine) -> HeadlessMenu:
    return HeadlessMenu(
        title='󰔊Speech Synthesis',
        items=[
            *(
                [
                    ActionItem(
                        key='download',
                        label='Download Piper Model',
                        icon='󰇚',
                        action=functools.partial(
                            download_piper_model,
                            callback=_download_model_callback,
                        ),
                    ),
                ]
                if not _is_piper_downloaded()
                else []
            ),
            SubMenuItem(
                key='select_engine',
                label='Select Engine',
                icon='󰔊',
                sub_menu=HeadlessMenu(
                    title='󰔊Select Engine' + selected_engine,
                    items=[
                        (
                            selection_parameters := SELECTED_ITEM_PARAMETERS
                            if engine == selected_engine
                            else UNSELECTED_ITEM_PARAMETERS,
                        )
                        and ActionItem(
                            label=ENGINE_LABELS[engine],
                            action=create_engine_selector(engine),
                            key=engine.name,
                            **selection_parameters,
                        )
                        for engine in SpeechSynthesisEngine
                        if _is_piper_downloaded()
                        or engine != SpeechSynthesisEngine.PIPER
                    ],
                ),
            ),
        ],
    )


def init_service() -> Subscriptions:
    """Initialize speech synthesis service."""
    access_key = secrets.read_secret(PICOVOICE_ACCESS_KEY)
    if access_key:
        to_thread(_context.set_access_key, access_key)
    else:
        to_thread(_context.cleanup)

    register_persistent_store(
        'speech_synthesis_engine',
        lambda state: state.speech_synthesis.selected_engine,
    )

    to_thread(_context.load_piper)

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.SPEECH,
            priority=1,
            menu_item=SubMenuItem(
                label='Speech Synthesis',
                icon='󰔊',
                sub_menu=_speech_synthesis_menu,
            ),
            key='engines',
        ),
    )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.SPEECH,
            priority=0,
            menu_item=SubMenuItem(
                label='Picovoice Settings',
                icon='PV',
                sub_menu=HeadedMenu(
                    title='Picovoice Settings',
                    heading='Picovoice',
                    sub_heading=_menu_sub_heading,
                    items=_menu_items,
                ),
            ),
            key='settings',
        ),
    )

    return [
        store.subscribe_event(
            SpeechSynthesisSynthesizeTextEvent,
            lambda event: to_thread(synthesize_and_play, event),
        ),
        _context.cleanup,
    ]
