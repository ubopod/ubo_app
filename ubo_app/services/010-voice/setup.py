"""Implement `init_service` for vocie module."""

from __future__ import annotations

import pathlib
import struct
from asyncio import CancelledError
from queue import Queue
from typing import TYPE_CHECKING, Any, cast

import fasteners
import pvorca
from piper.voice import PiperVoice  # pyright: ignore [reportMissingModuleSource]
from redux import FinishEvent
from ubo_gui.constants import SUCCESS_COLOR
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, SubMenuItem

from ubo_app.constants import PICOVOICE_ACCESS_KEY
from ubo_app.store.core import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioPlayAudioAction, AudioPlaybackDoneEvent
from ubo_app.store.services.notifications import NotificationExtraInformation
from ubo_app.store.services.voice import (
    VoiceEngine,
    VoiceReadTextAction,
    VoiceSetEngineAction,
    VoiceSynthesizeTextEvent,
    VoiceUpdateAccessKeyStatus,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task, to_thread
from ubo_app.utils.input import ubo_input
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _Context:
    picovoice_instance: pvorca.Orca | None = None
    piper_voice: PiperVoice | None = None
    picovoice_lock = fasteners.ReaderWriterLock()

    def cleanup(self: _Context) -> None:
        store.dispatch(VoiceUpdateAccessKeyStatus(is_access_key_set=False))
        with self.picovoice_lock.write_lock():
            if self.picovoice_instance:
                self.picovoice_instance.delete()
                self.picovoice_instance = None

    def set_access_key(self: _Context, access_key: str) -> None:
        store.dispatch(VoiceUpdateAccessKeyStatus(is_access_key_set=True))
        with self.picovoice_lock.write_lock():
            if access_key:
                if self.picovoice_instance:
                    self.picovoice_instance.delete()
                self.picovoice_instance = pvorca.create(access_key)

    def load_piper(self: _Context) -> None:
        self.piper_voice = PiperVoice.load(
            pathlib.Path(__file__)
            .parent.joinpath('models/kristin/en_US-kristin-medium.onnx')
            .resolve()
            .as_posix(),
        )


_context = _Context()


def input_access_key() -> None:
    """Input the Picovoice access key."""

    async def act() -> None:
        try:
            access_key = (
                await ubo_input(
                    title='Picovoice Access Key',
                    extra_information=NotificationExtraInformation(
                        text='Convert the Picovoice access key to a QR code and scan '
                        'it',
                    ),
                    prompt='Enter Picovoice Access Key',
                    fields=[],
                )
            )[0]
            secrets.write_secret(key=PICOVOICE_ACCESS_KEY, value=access_key)
            to_thread(_context.set_access_key, access_key)
        except CancelledError:
            pass

    create_task(act())


def clear_access_key() -> None:
    """Clear the Picovoice access key."""
    secrets.clear_secret(PICOVOICE_ACCESS_KEY)
    to_thread(_context.cleanup)


@store.view(lambda state: state.voice.selected_engine)
def _engine(engine: VoiceEngine) -> VoiceEngine:
    return engine


piper_cache: dict[str, list[bytes]] = {}


def synthesize_and_play(event: VoiceSynthesizeTextEvent) -> None:
    """Synthesize the text."""
    engine = _engine()
    if engine == VoiceEngine.PIPER:
        text = event.piper_text
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
    elif engine == VoiceEngine.PICOVOICE:
        with _context.picovoice_lock.read_lock():
            if not _context.picovoice_instance:
                return
            rate = _context.picovoice_instance.sample_rate

            audio_sequence = _context.picovoice_instance.synthesize(
                text=event.picovoice_text,
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


@store.autorun(lambda state: state.voice.is_access_key_set)
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


@store.autorun(lambda state: state.voice.is_access_key_set)
def _menu_sub_heading(_: bool | None) -> str:
    return f"""Set the access key
Current value: {secrets.read_covered_secret(PICOVOICE_ACCESS_KEY)}"""


ENGINE_LABELS = {
    VoiceEngine.PIPER: 'Piper',
    VoiceEngine.PICOVOICE: 'Picovoice',
}


def create_engine_selector(engine: VoiceEngine) -> Callable[[], None]:
    """Select the voice engine."""

    def _engine_selector() -> None:
        store.dispatch(
            VoiceSetEngineAction(engine=engine),
            VoiceReadTextAction(
                text={
                    VoiceEngine.PIPER: 'Piper voice engine selected',
                    VoiceEngine.PICOVOICE: 'Picovoice voice engine selected',
                }[engine],
                engine=engine,
            ),
        )

    return _engine_selector


@store.autorun(lambda state: state.voice.selected_engine)
def _voice_engine_items(selected_engine: VoiceEngine) -> Sequence[ActionItem]:
    selected_engine_parameters = {
        'background_color': SUCCESS_COLOR,
        'icon': '󰱒',
    }
    unselected_engine_parameters = {'icon': '󰄱'}
    return [
        ActionItem(
            label=ENGINE_LABELS[engine],
            action=create_engine_selector(engine),
            **cast(
                Any,
                selected_engine_parameters
                if engine == selected_engine
                else unselected_engine_parameters,
            ),
        )
        for engine in VoiceEngine
    ]


def init_service() -> None:
    """Initialize voice service."""
    access_key = secrets.read_secret(PICOVOICE_ACCESS_KEY)
    if access_key:
        to_thread(_context.set_access_key, access_key)
    else:
        to_thread(_context.cleanup)

    register_persistent_store(
        'voice_engine',
        lambda state: state.voice.selected_engine,
    )

    to_thread(_context.load_piper)

    store.subscribe_event(
        VoiceSynthesizeTextEvent,
        lambda event: to_thread(synthesize_and_play, event),
    )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.SPEECH,
            priority=1,
            menu_item=SubMenuItem(
                label='Voice Engine',
                icon='󰱑',
                sub_menu=HeadlessMenu(
                    title='󰱑Voice Engine',
                    items=_voice_engine_items,
                ),
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
                icon='󰔊',
                sub_menu=HeadedMenu(
                    title='Picovoice Settings',
                    heading='󰔊 Picovoice',
                    sub_heading=_menu_sub_heading,
                    items=_menu_items,
                ),
            ),
            key='settings',
        ),
    )

    store.subscribe_event(FinishEvent, _context.cleanup)
