"""Implement `init_service` for speech synthesis service."""

from __future__ import annotations

import struct
from asyncio import CancelledError
from typing import TYPE_CHECKING

import fasteners
import pvorca
from piper.voice import AudioChunk, PiperVoice
from redux import AutorunOptions

from ubo_app.constants.assistant import (
    PICOVOICE_ACCESS_KEY_SECRET_ID,
    PIPER_MODEL_PATH,
)
from ubo_app.engines.piper import PiperEngine
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import register_path_menu_matcher
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    QRCodeInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.audio import (
    AudioPlayAudioSampleAction,
    AudioPlayAudioSequenceAction,
    AudioSample,
)
from ubo_app.store.services.speech_synthesis import (
    ReadableInformation,
    SpeechSynthesisEngineName,
    SpeechSynthesisReadTextAction,
    SpeechSynthesisSetSelectedEngineAction,
    SpeechSynthesisSynthesizeTextEvent,
    SpeechSynthesisUpdateAccessKeyStatus,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task, to_thread
from ubo_app.utils.input import ubo_input
from ubo_app.utils.menu_items import build_selection_menu
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.utils.types import Subscriptions


_piper_engine = PiperEngine()


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
        if _piper_engine.is_setup:
            self.piper_voice = PiperVoice.load(PIPER_MODEL_PATH)


_context = _Context()


def input_access_key() -> None:
    """Input the Picovoice access key."""

    async def act() -> None:
        try:
            input_result = (
                await ubo_input(
                    prompt='Enter Picovoice Access Key',
                    title='Picovoice Access Key',
                    descriptions=[
                        QRCodeInputDescription(
                            pattern=r'^(?P<access_key>.*)$',
                            instructions=ReadableInformation(
                                text='Convert the Picovoice access key to a QR code '
                                'and hold it in front of the camera to scan it.',
                                picovoice_text='Convert the Picovoice access key to a '
                                '{QR|K Y UW AA R} and hold it in front of the camera '
                                'to scan it.',
                            ),
                        ),
                        WebUIInputDescription(
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
                        ),
                    ],
                )
            )[1]
            access_key = input_result.data.get('access_key')
            if not access_key:
                return
            secrets.write_secret(key=PICOVOICE_ACCESS_KEY_SECRET_ID, value=access_key)
            to_thread(_context.set_access_key, None, access_key)
        except CancelledError:
            pass

    create_task(act())


def clear_access_key() -> None:
    """Clear the Picovoice access key."""
    secrets.clear_secret(PICOVOICE_ACCESS_KEY_SECRET_ID)
    to_thread(_context.cleanup)


@store.with_state(lambda state: state.speech_synthesis.selected_engine)
def _engine(engine: SpeechSynthesisEngineName) -> SpeechSynthesisEngineName:
    return engine


piper_cache: dict[str, list[bytes]] = {}


def _get_audio_bytes(audio_item: AudioChunk | bytes) -> bytes:
    """Extract bytes from either AudioChunk or cached bytes."""
    if isinstance(audio_item, AudioChunk):
        return audio_item.audio_int16_bytes
    return audio_item


def synthesize_and_play(event: SpeechSynthesisSynthesizeTextEvent) -> None:
    """Synthesize the text."""
    engine = _engine()
    if engine == SpeechSynthesisEngineName.PIPER:
        text = event.information.piper_text
        if not _context.piper_voice:
            return
        id = hex(hash(text))

        if text in piper_cache:
            source = piper_cache[text]
            is_first_time = False
        else:
            source = _context.piper_voice.synthesize(text=text)
            piper_cache[text] = []
            is_first_time = True

        index = 0
        for audio_chunk in source:
            if audio_chunk:
                sample = _get_audio_bytes(audio_chunk)
                if is_first_time:
                    piper_cache[text].append(sample)
                store.dispatch(
                    AudioPlayAudioSequenceAction(
                        sample=AudioSample(
                            data=sample,
                            channels=1,
                            rate=_context.piper_voice.config.sample_rate,
                            width=2,
                        ),
                        id=id,
                        index=index,
                    ),
                )
                index += 1
        store.dispatch(
            AudioPlayAudioSequenceAction(
                sample=None,
                id=id,
                index=index,
            ),
        )

    elif engine == SpeechSynthesisEngineName.PICOVOICE:
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
            AudioPlayAudioSampleAction(
                sample=AudioSample(
                    data=sample,
                    channels=1,
                    rate=rate,
                    width=2,
                ),
            ),
        )


ENGINE_LABELS = {
    SpeechSynthesisEngineName.PIPER: 'Piper',
    SpeechSynthesisEngineName.PICOVOICE: 'Picovoice',
}


def create_engine_selector(engine: SpeechSynthesisEngineName) -> Callable[[], None]:
    """Select the speech synthesis engine."""

    def _engine_selector() -> None:
        store.dispatch(
            SpeechSynthesisSetSelectedEngineAction(engine_name=engine),
            SpeechSynthesisReadTextAction(
                information=ReadableInformation(
                    text={
                        SpeechSynthesisEngineName.PIPER: 'Piper speech synthesis '
                        'engine selected',
                        SpeechSynthesisEngineName.PICOVOICE: 'Picovoice speech '
                        'synthesis engine selected',
                    }[engine],
                ),
                engine=engine,
            ),
        )

    return _engine_selector


SPEECH_SYNTHESIS_MENU_ID = 'speech-synthesis:main'
PICOVOICE_SETTINGS_MENU_ID = 'speech-synthesis:picovoice'


def _download_piper_wrapper() -> None:
    """Download Piper model and reload context after completion."""
    _piper_engine.setup()


def _register_speech_synthesis_action_handlers() -> None:
    """Register action handlers for speech synthesis menu items."""
    from ubo_app.store.core.action_registry import register_action

    register_action(
        'speech-synthesis:download_piper',
        _download_piper_wrapper,
        allow_reregister=True,
    )
    register_action(
        'speech-synthesis:set_access_key',
        input_access_key,
        allow_reregister=True,
    )
    register_action(
        'speech-synthesis:clear_access_key',
        clear_access_key,
        allow_reregister=True,
    )
    register_action(
        'speech-synthesis:select_engine',
        lambda: store.dispatch(
            StackPushMenuAction(menu_key='speech-synthesis:engines'),
        ),
        allow_reregister=True,
    )

    # Register engine-specific actions
    for engine in SpeechSynthesisEngineName:
        if _piper_engine.is_setup or engine != SpeechSynthesisEngineName.PIPER:
            register_action(
                f'speech-synthesis:engine:{engine.value}',
                create_engine_selector(engine),
                allow_reregister=True,
            )


@store.autorun(
    lambda state: (
        state.speech_synthesis.selected_engine,
        state.assistant.provider_setup_status,
    ),
    options=AutorunOptions(memoization=False),
)
def update_speech_synthesis_dynamic_menu(
    _data: tuple[SpeechSynthesisEngineName, object],
) -> None:
    """Update the dynamic menu for speech synthesis (dumb UI)."""
    _register_speech_synthesis_action_handlers()

    if _piper_engine.is_setup and _context.piper_voice is None:
        to_thread(_context.load_piper)

    items: list[MenuItemData] = []

    # Add download option if Piper not downloaded
    if not _piper_engine.is_setup:
        items.append(
            MenuItemData(
                key='download',
                label='Download Piper Model',
                icon='󰇚',
                action_id='speech-synthesis:download_piper',
            ),
        )

    # Add engine selection submenu item
    items.append(
        MenuItemData(
            key='select_engine',
            label='Select Engine',
            icon='󰔊',
            action_id='speech-synthesis:select_engine',
        ),
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=SPEECH_SYNTHESIS_MENU_ID,
            title='󰔊Speech Synthesis',
            items=tuple(items),
            placeholder='',
        ),
    )


SPEECH_SYNTHESIS_ENGINES_MENU_ID = 'speech-synthesis:engines'


@store.autorun(
    lambda state: (
        state.speech_synthesis.selected_engine,
        state.assistant.provider_setup_status,
    ),
    options=AutorunOptions(memoization=False),
)
def update_engines_dynamic_menu(
    data: tuple[SpeechSynthesisEngineName, object],
) -> None:
    """Update the dynamic menu for engine selection."""
    selected_engine = SpeechSynthesisEngineName(data[0])
    available_engines = [
        engine
        for engine in SpeechSynthesisEngineName
        if _piper_engine.is_setup or engine != SpeechSynthesisEngineName.PIPER
    ]

    build_selection_menu(
        options=tuple(
            (
                engine.name,
                ENGINE_LABELS[engine],
                f'speech-synthesis:engine:{engine.value}',
            )
            for engine in available_engines
        ),
        selected_key=selected_engine.name,
        menu_id=SPEECH_SYNTHESIS_ENGINES_MENU_ID,
        title=f'󰔊Select Engine: {selected_engine}',
        heading='Select Active Engine',
        sub_heading='Choose the speech synthesis engine to use',
    )


@store.autorun(lambda state: state.speech_synthesis.is_access_key_set)
def update_picovoice_dynamic_menu(
    is_access_key_set: bool | None,  # noqa: FBT001
) -> None:
    """Update the dynamic menu for Picovoice settings (dumb UI)."""
    if is_access_key_set:
        items = (
            MenuItemData(
                key='clear_key',
                label='Clear Access Key',
                icon='󰌊',
                action_id='speech-synthesis:clear_access_key',
            ),
        )
    else:
        items = (
            MenuItemData(
                key='set_key',
                label='Set Access Key',
                icon='󰐲',
                action_id='speech-synthesis:set_access_key',
            ),
        )

    # Get covered secret for sub_heading
    covered_secret = secrets.read_covered_secret(PICOVOICE_ACCESS_KEY_SECRET_ID)
    sub_heading = f'Set the access key\nCurrent value: {covered_secret}'

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=PICOVOICE_SETTINGS_MENU_ID,
            title='Picovoice Settings',
            heading='Picovoice',
            sub_heading=sub_heading,
            items=items,
            placeholder='',
        ),
    )


def init_service() -> Subscriptions:
    """Initialize speech synthesis service."""

    # Register path matchers for speech synthesis settings navigation
    def _speech_synthesis_path_matcher(path: tuple[str, ...]) -> str | None:
        if len(path) >= 4:  # noqa: PLR2004
            service_key = path[3]
            if service_key == 'speech_synthesis:engines':
                if len(path) == 4:  # noqa: PLR2004
                    return SPEECH_SYNTHESIS_MENU_ID
                # Engines submenu
                if len(path) == 5 and path[4] == 'speech-synthesis:engines':  # noqa: PLR2004
                    return SPEECH_SYNTHESIS_ENGINES_MENU_ID
            if service_key == 'speech_synthesis:settings':
                return PICOVOICE_SETTINGS_MENU_ID
        return None

    unregister_path_matcher = register_path_menu_matcher(
        'speech-synthesis:settings',
        _speech_synthesis_path_matcher,
    )

    access_key = secrets.read_secret(PICOVOICE_ACCESS_KEY_SECRET_ID)
    if access_key:
        to_thread(_context.set_access_key, None, access_key)
    else:
        to_thread(_context.cleanup)

    register_persistent_store(
        'speech_synthesis:selected_engine',
        lambda state: state.speech_synthesis.selected_engine,
    )

    to_thread(_context.load_piper)

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ACCESSIBILITY,
            priority=10,
            label='Speech Synthesis',
            icon='󰔊',
            key='engines',
        ),
    )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ACCESSIBILITY,
            priority=0,
            label='Picovoice Settings',
            icon='PV',
            key='settings',
        ),
    )

    return [
        store.subscribe_event(
            SpeechSynthesisSynthesizeTextEvent,
            lambda event: to_thread(synthesize_and_play, None, event),
        ),
        _context.cleanup,
        unregister_path_matcher,
    ]
