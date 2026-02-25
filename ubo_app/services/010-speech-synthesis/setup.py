"""Implement `init_service` for speech synthesis service."""

from __future__ import annotations

import struct
from asyncio import CancelledError
from typing import TYPE_CHECKING

import fasteners
import pvorca
from piper.voice import AudioChunk, PiperVoice
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadlessMenu, SubMenuItem

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
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
)
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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


@store.autorun(lambda state: state.speech_synthesis.is_access_key_set)
def _menu_items(is_access_key_set: bool | None) -> Sequence[ActionItem]:  # noqa: FBT001
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
def _menu_sub_heading(_: bool | None) -> str:  # noqa: FBT001
    return f"""Set the access key
Current value: {secrets.read_covered_secret(PICOVOICE_ACCESS_KEY_SECRET_ID)}"""


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


SPEECH_SYNTHESIS_MENU_ID = 'speech-synthesis:main'
PICOVOICE_SETTINGS_MENU_ID = 'speech-synthesis:picovoice'



@store.autorun(
    lambda state: (
        state.speech_synthesis.selected_engine,
        state.assistant.provider_setup_status,
    ),
    options=AutorunOptions(memoization=False),
)
def _speech_synthesis_menu(
    data: tuple[SpeechSynthesisEngineName, dict[str, bool]],
) -> HeadlessMenu:
    selected_engine, _ = data

    if _piper_engine.is_setup and _context.piper_voice is None:
        to_thread(_context.load_piper)

    return HeadlessMenu(
        title='󰔊Speech Synthesis',
        items=[
            *(
                [
                    ActionItem(
                        key='download',
                        label='Setup Piper',
                        icon='󰇚',
                        action=_piper_engine.setup,
                    ),
                ]
                if not _piper_engine.is_setup
                else []
            ),
            SubMenuItem(
                key='select_engine',
                label='Select Engine',
                icon='󰔊',
                sub_menu=HeadlessMenu(
                    title=f'󰔊Select Engine: {selected_engine}',
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
                        for engine in SpeechSynthesisEngineName
                        if _piper_engine.is_setup
                        or engine != SpeechSynthesisEngineName.PIPER
                    ],
                ),
            ),
        ],
    )


def _download_piper_wrapper() -> None:
    """Download Piper model and reload context after completion."""
    download_piper_model(callback=_context.load_piper)


def _register_speech_synthesis_action_handlers() -> None:
    """Register action handlers for speech synthesis menu items."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
    )

    # Only register once
    if 'speech-synthesis:download_piper' in get_registered_actions():
        return

    register_action('speech-synthesis:download_piper', _download_piper_wrapper)
    register_action('speech-synthesis:set_access_key', input_access_key)
    register_action('speech-synthesis:clear_access_key', clear_access_key)
    register_action(
        'speech-synthesis:select_engine',
        lambda: store.dispatch(
            StackPushMenuAction(menu_key='speech-synthesis:engines'),
        ),
    )

    # Register engine-specific actions
    for engine in SpeechSynthesisEngineName:
        if _is_piper_downloaded() or engine != SpeechSynthesisEngineName.PIPER:
            register_action(
                f'speech-synthesis:engine:{engine.value}',
                create_engine_selector(engine),
            )


@store.autorun(
    lambda state: state.speech_synthesis.selected_engine,
    options=AutorunOptions(memoization=False),
)
def update_speech_synthesis_dynamic_menu(
    _selected_engine: SpeechSynthesisEngineName,
) -> None:
    """Update the dynamic menu for speech synthesis (dumb UI)."""
    _register_speech_synthesis_action_handlers()

    items: list[MenuItemData] = []

    # Add download option if Piper not downloaded
    if not _is_piper_downloaded():
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
    lambda state: state.speech_synthesis.selected_engine,
    options=AutorunOptions(memoization=False),
)
def update_engines_dynamic_menu(
    selected_engine: SpeechSynthesisEngineName,
) -> None:
    """Update the dynamic menu for engine selection."""
    items: list[MenuItemData] = []
    for engine in SpeechSynthesisEngineName:
        if _is_piper_downloaded() or engine != SpeechSynthesisEngineName.PIPER:
            is_selected = engine == selected_engine
            items.append(
                MenuItemData(
                    key=engine.name,
                    label=ENGINE_LABELS[engine],
                    icon=SELECTED_ITEM_PARAMETERS['icon']
                    if is_selected
                    else UNSELECTED_ITEM_PARAMETERS['icon'],
                    action_id=f'speech-synthesis:engine:{engine.value}',
                    background_color=SELECTED_ITEM_PARAMETERS.get(
                        'background_color',
                    )
                    if is_selected
                    else None,
                ),
            )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=SPEECH_SYNTHESIS_ENGINES_MENU_ID,
            title=f'󰔊Select Engine: {selected_engine}',
            heading='Select Active Engine',
            sub_heading='Choose the speech synthesis engine to use',
            items=tuple(items),
            placeholder='',
        ),
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
