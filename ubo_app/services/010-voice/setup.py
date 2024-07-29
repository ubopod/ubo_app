"""Implement `init_service` for vocie module."""

from __future__ import annotations

import pathlib
import struct
from asyncio import CancelledError
from queue import Queue
from threading import Lock
from typing import TYPE_CHECKING, Any, cast

import pvorca
from piper.voice import PiperVoice  # pyright: ignore [reportMissingModuleSource]
from redux import FinishEvent
from ubo_gui.constants import SUCCESS_COLOR
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, SubMenuItem

from ubo_app.constants import PICOVOICE_ACCESS_KEY
from ubo_app.store.core import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import autorun, dispatch, subscribe_event, view
from ubo_app.store.services.audio import AudioPlayAudioAction, AudioPlaybackDoneEvent
from ubo_app.store.services.voice import (
    VoiceEngine,
    VoiceReadTextAction,
    VoiceSetEngineAction,
    VoiceSynthesizeTextEvent,
    VoiceUpdateAccessKeyStatus,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task, to_thread
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.qrcode import qrcode_input

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _Context:
    orca_instance: pvorca.Orca | None = None
    piper_voice: PiperVoice | None = None
    orca_lock: Lock = Lock()

    def cleanup(self: _Context) -> None:
        dispatch(VoiceUpdateAccessKeyStatus(is_access_key_set=False))
        with self.orca_lock:
            if self.orca_instance:
                self.orca_instance.delete()
                self.orca_instance = None

    def set_access_key(self: _Context, access_key: str) -> None:
        dispatch(VoiceUpdateAccessKeyStatus(is_access_key_set=True))
        with self.orca_lock:
            if access_key:
                if self.orca_instance:
                    self.orca_instance.delete()
                self.orca_instance = pvorca.create(access_key)

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
                await qrcode_input(
                    '.*',
                    prompt='Convert the Picovoice access key to a QR code and '
                    'scan it.',
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


@view(lambda state: state.voice.selected_engine)
def _engine(engine: str) -> str:
    return engine


piper_cache: dict[str, list[bytes]] = {}


def synthesize_and_play(event: VoiceSynthesizeTextEvent) -> None:
    """Synthesize the text."""
    engine = _engine()
    if engine == 'piper':
        text = event.piper_text
        if not _context.piper_voice:
            return
        if text in piper_cache:
            source = piper_cache[text]
        else:
            source = _context.piper_voice.synthesize_stream_raw(text)

        queue = Queue(maxsize=1)
        queue.put(None)

        unsubscribe = subscribe_event(
            AudioPlaybackDoneEvent,
            lambda event: event.id == id and queue.get(),
        )

        piper_cache[text] = []
        id = hex(hash(text))
        for sample in source:
            piper_cache[text].append(sample)
            dispatch(
                AudioPlayAudioAction(
                    id=id,
                    sample=sample,
                    channels=1,
                    rate=22050,
                    width=2,
                ),
            )
            queue.put(None)
        unsubscribe()
    elif engine == 'orca':
        with _context.orca_lock:
            if not _context.orca_instance:
                return
            rate = _context.orca_instance.sample_rate

            audio_sequence = _context.orca_instance.synthesize(
                text=event.orca_text,
                speech_rate=event.speech_rate,
            )
            sample = b''.join(struct.pack('h', sample) for sample in audio_sequence[0])
            dispatch(
                AudioPlayAudioAction(
                    sample=sample,
                    channels=1,
                    rate=rate,
                    width=2,
                ),
            )


@autorun(lambda state: state.voice.is_access_key_set)
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


@autorun(lambda state: state.voice.is_access_key_set)
def _menu_sub_heading(_: bool | None) -> str:
    return f"""Set the access key
Current value: {secrets.read_covered_secret(PICOVOICE_ACCESS_KEY)}"""


ENGINE_LABELS = {
    VoiceEngine.PIPER: 'Piper',
    VoiceEngine.ORCA: 'Orca',
}


@autorun(lambda state: state.voice.selected_engine)
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
                if engine is selected_engine
                else unselected_engine_parameters,
            ),
        )
        for engine in VoiceEngine
    ]


def create_engine_selector(engine: VoiceEngine) -> Callable[[], None]:
    """Select the voice engine."""

    def _engine_selector() -> None:
        dispatch(
            VoiceSetEngineAction(engine=engine),
            VoiceReadTextAction(
                text={
                    VoiceEngine.PIPER: 'Piper voice engine selected',
                    VoiceEngine.ORCA: 'Orca voice engine selected',
                }[engine],
                engine=engine,
            ),
        )

    return _engine_selector


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

    subscribe_event(
        VoiceSynthesizeTextEvent,
        lambda event: to_thread(synthesize_and_play, event),
    )

    dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ACCESSIBILITY,
            priority=0,
            menu_item=SubMenuItem(
                label='Voice',
                icon='󰔊',
                sub_menu=HeadlessMenu(
                    title='󰔊Voice',
                    items=[
                        SubMenuItem(
                            label='Voice Engine',
                            icon='󰱑',
                            sub_menu=HeadlessMenu(
                                title='󰱑Voice Engine',
                                items=_voice_engine_items,
                            ),
                        ),
                        SubMenuItem(
                            label='Orca Settings',
                            icon='󰔊',
                            sub_menu=HeadedMenu(
                                title='Orca Settings',
                                heading='󰔊 Picovoice',
                                sub_heading=_menu_sub_heading,
                                items=_menu_items,
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )

    subscribe_event(FinishEvent, _context.cleanup)
