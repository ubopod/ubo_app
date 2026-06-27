"""Wake-up menu tree, trigger/IR forms, and their action handlers.

Extracted from ``setup.py``: the self-contained wake-word UI cluster (the mode-
first menu builders, the add/edit/remove trigger + Infrared + model-management
forms, and the navigation/edit handlers that drive them). ``setup.py`` imports
only :func:`dispatch_wake_menus` (called from its menu autorun) and
:func:`register_wake_handlers` (called from ``init_service``); nothing here calls
back into ``setup.py``.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from commands import (
    MODE_BINDABLE_KEY,
)
from openwakeword_engine import (
    MODELS_DIR,
    helpers_available,
    scan_models,
    validate_openwakeword_model,
)
from wake_phrase_validation import (
    phrase_collisions,
    validate_phrase,
)

from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuItemData,
    StackPopAction,
    StackPushMenuAction,
    StackPushPromptAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    DEFAULT_VOSK_MODEL_ID,
    AssistantSetConversationEndPhrasesAction,
)
from ubo_app.store.services.infrared import (
    InfraredAddDeviceAction,
    InfraredDevice,
)
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionSetConversationEndPhrasesAction,
    SpeechRecognitionState,
    WakeEngineSetEnabledAction,
    WakeMode,
    WakeTriggerAddAction,
    WakeTriggerRemoveAction,
    WakeWordDeleteModelAction,
    WakeWordDownloadModelsAction,
    WakeWordEngineConfig,
    WakeWordEngineName,
    WakeWordModelStatus,
    WakeWordSetAvailableModelsAction,
    WakeWordTrigger,
    engine_config,
    trigger_by_id,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from engines_manager import EnginesManager

    from ubo_app.utils.types import Subscriptions


def _build_toggle_item(
    *,
    key: str,
    label: str,
    is_active: bool,
    action_id: str,
) -> MenuItemData:
    """Build a MenuItemData for a toggle-style menu item."""
    params = SELECTED_ITEM_PARAMETERS if is_active else UNSELECTED_ITEM_PARAMETERS
    return MenuItemData(
        key=key,
        label=label,
        icon=params.get('icon', ''),
        color=params.get('color', '#ffffff'),
        background_color=params.get('background_color'),
        action_id=action_id,
    )


# Per-mode short title + helper text (title used for menu rows + submenu heading).
_WAKE_MODE_META: dict[WakeMode, tuple[str, str]] = {
    WakeMode.INTENTS: ('Shortcut', 'Triggers a voice shortcut.'),
    WakeMode.QUICK_CHAT: ('Short Chat', 'Starts a short chat.'),
    WakeMode.CONVERSATION: ('Conversation', 'Starts a long conversation.'),
    WakeMode.STOP_TALKING: ('Silence', 'Stops the assistant talking.'),
}
# All four modes are grouped under "Phrases" (including Silence = STOP_TALKING).
_PHRASE_MODES: tuple[WakeMode, ...] = (
    WakeMode.INTENTS,
    WakeMode.QUICK_CHAT,
    WakeMode.CONVERSATION,
    WakeMode.STOP_TALKING,
)
_END_PHRASES_LABEL = 'Conversation End'


@store.with_state(lambda state: state.speech_recognition)
def _read_speech_recognition_state(
    state: SpeechRecognitionState,
) -> SpeechRecognitionState:
    return state


def _notify_blocked_no_model() -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='speech_recognition:wake-phrase-no-model',
                title='Model required',
                content='Download the Vosk speech model before editing wake phrases.',
                importance=Importance.HIGH,
                display_type=NotificationDisplayType.FLASH,
                icon='',
            ),
        ),
    )


def _notify_rejected(problems: list[str]) -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='speech_recognition:wake-phrase-rejected',
                title='Phrase not accepted',
                content='\n'.join(problems),
                importance=Importance.HIGH,
                display_type=NotificationDisplayType.FLASH,
                icon='',
            ),
        ),
    )


def _clean_phrase_lines(raw: str) -> list[str]:
    """Lowercased, de-duplicated, non-empty phrase lines."""
    lines: list[str] = []
    for line in raw.splitlines():
        phrase = line.strip().casefold()
        if phrase and phrase not in lines:
            lines.append(phrase)
    return lines


# --- Web UI trigger editing (multi-step: pick source, then provide a value) ---

_SOURCE_VOSK = 'Vosk'
_SOURCE_OPENWAKEWORD = 'OpenWakeWord'
_SOURCE_PICOVOICE = 'Picovoice'
_SOURCE_INFRARED = 'Infrared'
_SOURCE_ORDER: tuple[str, ...] = (
    _SOURCE_VOSK,
    _SOURCE_OPENWAKEWORD,
    _SOURCE_PICOVOICE,
    _SOURCE_INFRARED,
)
def _notify_setup_required(message: str) -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='speech_recognition:wake-trigger-setup',
                title='Setup required',
                content=message,
                importance=Importance.HIGH,
                display_type=NotificationDisplayType.FLASH,
                icon='',
            ),
        ),
    )


@store.with_state(lambda state: state.infrared.registered_devices)
def _read_ir_devices(devices: list[InfraredDevice]) -> list[InfraredDevice]:
    """Snapshot the registered Infrared devices (cross-slice read)."""
    return list(devices)


def _find_ir_device(protocol: str, scancode: str) -> InfraredDevice | None:
    """Return the registered Infrared device for (protocol, scancode), or None."""
    return next(
        (
            device
            for device in _read_ir_devices()
            if device.protocol == protocol and device.scancode == scancode
        ),
        None,
    )


@store.with_state(
    lambda state: (
        state.assistant.selected_vosk_model,
        state.assistant.vosk_downloaded_models,
    ),
)
def _vosk_model_downloaded(data: tuple[str, tuple[str, ...]]) -> bool:
    """Whether the active Vosk model is downloaded (on disk), not merely loaded.

    Readiness is about the model existing on disk; the engine loads it lazily, so
    ``wake_word_model()`` (the in-memory Kaldi model) can still be None right after
    a fresh download. Mirrors the Voice Shortcuts menu's availability check.
    """
    selected, downloaded = data
    return (selected or DEFAULT_VOSK_MODEL_ID) in downloaded


def _source_unavailable(
    source: str,
    state: SpeechRecognitionState,
    ir_devices: list[InfraredDevice],
) -> tuple[str, str] | None:
    """If *source* can't take a trigger, return ``(label_suffix, notice)``.

    Returns None when the source is ready. The label suffix is shown in the
    dropdown (the Web UI SELECT can't truly disable an option); the notice is
    flashed if the user picks the source and presses Provide anyway.
    """
    if source == _SOURCE_VOSK:
        if not _vosk_model_downloaded():
            return (
                '(model needed)',
                'Download the Vosk speech model before adding a Vosk phrase '
                '(Voice Shortcuts → Download Vosk).',
            )
        return None
    if source == _SOURCE_OPENWAKEWORD:
        config = engine_config(state, WakeWordEngineName.OPENWAKEWORD)
        if config is None or not config.enabled:
            return (
                '(disabled)',
                'Enable OpenWakeWord first '
                '(Wake Up → Engines → OpenWakeWord → Enable Engine).',
            )
        if not state.openwakeword_models:
            return (
                '(no models)',
                'Download or upload an OpenWakeWord model first '
                '(Wake Up → Engines → OpenWakeWord).',
            )
        return None
    if source == _SOURCE_INFRARED:
        if not ir_devices:
            return (
                '(no keys)',
                'Register an Infrared remote key first (Settings → Infrared) '
                'before assigning one here.',
            )
        return None
    return ('(coming soon)', "Picovoice isn't supported yet.")  # dormant


def _source_options(
    state: SpeechRecognitionState,
    ir_devices: list[InfraredDevice],
) -> list[str]:
    """All sources, annotating any that aren't ready with a short reason."""
    options: list[str] = []
    for source in _SOURCE_ORDER:
        unavailable = _source_unavailable(source, state, ir_devices)
        options.append(
            source if unavailable is None else f'{source} {unavailable[0]}',
        )
    return options


def _parse_source(label: str) -> str:
    """Strip any ``(reason)`` suffix back to the base source name."""
    return next((s for s in _SOURCE_ORDER if label.startswith(s)), label)


async def _add_trigger_form(mode: WakeMode, engines_manager: EnginesManager) -> None:
    """Step 1: pick the trigger source, then open its value form (step 2)."""
    title = _WAKE_MODE_META[mode][0]
    state = _read_speech_recognition_state()
    ir_devices = _read_ir_devices()
    options = _source_options(state, ir_devices)
    try:
        _, result = await ubo_input(
            prompt=f'Add a {title} trigger',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='source',
                            label='Trigger Source',
                            type=InputFieldType.SELECT,
                            description='Which engine or input triggers this.',
                            options=options,
                            default_value=options[0],
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if result is None:
        return
    source = _parse_source(result.data.get('source', '') or '')
    # Warn right here (on Provide), re-reading fresh state, instead of opening an
    # empty step-2 form.
    unavailable = _source_unavailable(
        source,
        _read_speech_recognition_state(),
        _read_ir_devices(),
    )
    if unavailable is not None:
        _notify_setup_required(unavailable[1])
        return
    await _provide_value_form(mode, source, engines_manager, replace_target=None)


async def _provide_value_form(
    mode: WakeMode,
    source: str,
    engines_manager: EnginesManager,
    replace_target: WakeWordTrigger | InfraredDevice | None,
) -> None:
    """Step 2: collect the source-specific value and save (replacing if editing)."""
    if source == _SOURCE_VOSK:
        await _vosk_value_form(mode, engines_manager, replace_target)
    elif source == _SOURCE_OPENWAKEWORD:
        await _openwakeword_value_form(mode, replace_target)
    elif source == _SOURCE_INFRARED:
        await _infrared_value_form(mode, replace_target)
    else:
        _notify_setup_required("Picovoice isn't configured yet.")


async def _vosk_value_form(
    mode: WakeMode,
    engines_manager: EnginesManager,
    replace_target: WakeWordTrigger | InfraredDevice | None,
) -> None:
    """Type a Vosk phrase; validate it against the Vosk vocab + collisions."""
    if not _vosk_model_downloaded():
        _notify_blocked_no_model()
        return
    # The in-memory Kaldi model is only needed for vocab validation; it loads
    # lazily, so it may be None even though the model is downloaded — in that case
    # we skip the vocab check (collisions are still enforced).
    model = engines_manager.wake_word_model()
    title = _WAKE_MODE_META[mode][0]
    old = replace_target if isinstance(replace_target, WakeWordTrigger) else None
    try:
        _, result = await ubo_input(
            prompt=f'{"Edit" if old else "Add"} {title} phrase',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='phrase',
                            label='Phrase',
                            type=InputFieldType.TEXT,
                            description='A short spoken phrase for Vosk to detect.',
                            default_value=old.value if old else None,
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if result is None:
        return
    phrase = (result.data.get('phrase', '') or '').strip().casefold()
    if not phrase or (old is not None and phrase == old.value):
        return
    state = _read_speech_recognition_state()
    problems = (
        [f'"{phrase}": {p}' for p in validate_phrase(phrase, model)]
        if model is not None
        else []
    )
    problems += [
        f'"{phrase}": {p}'
        for p in phrase_collisions(phrase, WakeWordEngineName.VOSK, state)
    ]
    if problems:
        _notify_rejected(problems)
        return
    actions: list[object] = []
    if old is not None:
        actions.append(
            WakeTriggerRemoveAction(engine=WakeWordEngineName.VOSK, id=old.id),
        )
    actions.append(
        WakeTriggerAddAction(
            engine=WakeWordEngineName.VOSK,
            id=uuid4().hex,
            label=phrase,
            mode=mode,
            value=phrase,
        ),
    )
    store.dispatch(*actions)


def _parse_sensitivity(raw: str | None) -> float:
    """Parse a 0-100 slider string into a 0.0-1.0 sensitivity (default 0.5)."""
    try:
        percent = float(raw) if raw not in (None, '') else 50.0
    except (TypeError, ValueError):
        percent = 50.0
    return max(0.0, min(1.0, percent / 100))


async def _openwakeword_value_form(
    mode: WakeMode,
    replace_target: WakeWordTrigger | InfraredDevice | None,
) -> None:
    """Pick a downloaded OpenWakeWord model (+ name + sensitivity) for *mode*."""
    state = _read_speech_recognition_state()
    config = engine_config(state, WakeWordEngineName.OPENWAKEWORD)
    models = list(state.openwakeword_models)
    if config is None or not config.enabled or not models:
        _notify_setup_required(
            'Enable OpenWakeWord and download or upload a model first '
            '(Wake Up → Engines → OpenWakeWord).',
        )
        return
    title = _WAKE_MODE_META[mode][0]
    old = replace_target if isinstance(replace_target, WakeWordTrigger) else None
    default_model = old.value if old and old.value in models else models[0]
    try:
        _, result = await ubo_input(
            prompt=f'{"Edit" if old else "Add"} {title} model',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='model',
                            label='Model',
                            type=InputFieldType.SELECT,
                            description='An OpenWakeWord model to detect.',
                            options=models,
                            default_value=default_model,
                            required=True,
                        ),
                        InputFieldDescription(
                            name='name',
                            label='Name',
                            type=InputFieldType.TEXT,
                            description='Optional label shown in the list.',
                            default_value=old.label if old else None,
                        ),
                        InputFieldDescription(
                            name='sensitivity',
                            label='Sensitivity',
                            type=InputFieldType.RANGE,
                            description='Higher triggers more readily (and risks '
                            'more false activations).',
                            default_value=str(
                                round((old.sensitivity if old else 0.5) * 100),
                            ),
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if result is None:
        return
    stem = (result.data.get('model', '') or '').strip()
    if stem not in models:
        return
    name = (result.data.get('name', '') or '').strip() or stem
    sensitivity = _parse_sensitivity(result.data.get('sensitivity'))
    # A model stem maps to a single trigger id in the engine, so the same model used
    # twice (any mode, including this one) would silently collapse to one binding —
    # reject a stem already used by another trigger, ignoring the one being edited.
    collisions = phrase_collisions(
        stem,
        WakeWordEngineName.OPENWAKEWORD,
        _read_speech_recognition_state(),
        exclude_trigger_id=old.id if old is not None else None,
    )
    if collisions:
        _notify_rejected(collisions)
        return
    actions: list[object] = []
    if old is not None:
        actions.append(
            WakeTriggerRemoveAction(
                engine=WakeWordEngineName.OPENWAKEWORD,
                id=old.id,
            ),
        )
    actions.append(
        WakeTriggerAddAction(
            engine=WakeWordEngineName.OPENWAKEWORD,
            id=uuid4().hex,
            label=name,
            mode=mode,
            value=stem,
            sensitivity=sensitivity,
        ),
    )
    store.dispatch(*actions)


async def _infrared_value_form(
    mode: WakeMode,
    replace_target: WakeWordTrigger | InfraredDevice | None,
) -> None:
    """Pick a registered Infrared remote key and bind it to *mode*."""
    ir_devices = _read_ir_devices()
    if not ir_devices:
        _notify_setup_required(
            'Register an Infrared remote key first (Settings → Infrared).',
        )
        return
    title = _WAKE_MODE_META[mode][0]
    names = [device.name for device in ir_devices]
    old = replace_target if isinstance(replace_target, InfraredDevice) else None
    default_name = old.name if old and old.name in names else names[0]
    try:
        _, result = await ubo_input(
            prompt=f'{"Edit" if old else "Add"} {title} remote key',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='device',
                            label='Remote Key',
                            type=InputFieldType.SELECT,
                            description='A registered Infrared remote key.',
                            options=names,
                            default_value=default_name,
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if result is None:
        return
    device = next(
        (d for d in ir_devices if d.name == result.data.get('device', '')),
        None,
    )
    if device is None:
        return
    actions: list[object] = []
    # Editing to a different key: unbind the previous one (keep it registered).
    if old is not None and (old.protocol, old.scancode) != (
        device.protocol,
        device.scancode,
    ):
        actions.append(
            InfraredAddDeviceAction(
                name=old.name,
                protocol=old.protocol,
                scancode=old.scancode,
                description=old.description,
                bound_action_key=None,
            ),
        )
    actions.append(
        InfraredAddDeviceAction(
            name=device.name,
            protocol=device.protocol,
            scancode=device.scancode,
            description=device.description,
            bound_action_key=MODE_BINDABLE_KEY[mode],
        ),
    )
    store.dispatch(*actions)


async def _end_phrases_form(engines_manager: EnginesManager) -> None:
    """Edit the conversation end phrases (multiple alternatives, one per line).

    End phrases are an assistant-conversation policy, not tied to any one wake
    engine, so editing isn't gated on the Vosk model: when the Kaldi model is
    loaded its vocabulary is validated; when it isn't (OpenWakeWord/IR-only users),
    only the empty/duplicate and wake-phrase-collision checks run.
    """
    model = engines_manager.wake_word_model()

    raw = '\n'.join(_read_speech_recognition_state().conversation_end_phrases)
    try:
        _, result = await ubo_input(
            prompt=f'Edit {_END_PHRASES_LABEL}',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='phrases',
                            label=_END_PHRASES_LABEL,
                            type=InputFieldType.LONG,
                            description='One phrase per line, spoken to end a '
                            'conversation.',
                            default_value=raw,
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        logger.info('End phrases form cancelled')
        return

    raw = (result.data.get('phrases', '') if result else '') or ''
    lines = _clean_phrase_lines(raw)
    state = _read_speech_recognition_state()
    wake_values = {
        trigger.value.casefold()
        for config in state.wake_engines
        for trigger in config.triggers
    }
    problems: list[str] = []
    if not lines:
        problems.append('Enter at least one phrase.')
    for phrase in lines:
        if model is not None:
            problems += [
                f'"{phrase}": {p}' for p in validate_phrase(phrase, model)
            ]
        if phrase in wake_values:
            problems.append(f'"{phrase}": already used by a wake phrase.')
    if problems:
        _notify_rejected(problems)
        return
    store.dispatch(
        SpeechRecognitionSetConversationEndPhrasesAction(phrases=tuple(lines)),
    )


_ENGINE_LABELS: dict[WakeWordEngineName, str] = {
    WakeWordEngineName.VOSK: 'Vosk',
    WakeWordEngineName.OPENWAKEWORD: 'OpenWakeWord',
}
def _engine_label(engine: WakeWordEngineName) -> str:
    return _ENGINE_LABELS.get(engine, engine.value)


def _model_stem(filename: str, label: str) -> str:
    """Derive a filesystem-safe model stem from the upload filename / label."""
    base = Path(filename).stem or label
    slug = re.sub(r'[^a-z0-9]+', '_', base.casefold()).strip('_')
    return slug or 'wake_model'


async def _upload_model_form(engine: WakeWordEngineName) -> None:
    """Upload a custom OpenWakeWord ``.onnx`` model into the engine's pool.

    The model is added to the available pool only; it is assigned to a mode later
    from Wake Up → Phrases → <mode> → Add → OpenWakeWord.
    """
    try:
        _, result = await ubo_input(
            prompt='Upload a wake-word model',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='label',
                            label='Name',
                            type=InputFieldType.TEXT,
                            description='A name for this model.',
                            required=True,
                        ),
                        InputFieldDescription(
                            name='model_file',
                            label='Model File',
                            type=InputFieldType.FILE,
                            description='An OpenWakeWord .onnx model.',
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if result is None:
        return

    data = result.data
    label = (data.get('label') or '').strip()
    upload_id = data.get('model_file_upload_id')
    filename = data.get('model_file_name', '')
    if not label or not upload_id:
        return

    from ubo_app.utils.file_upload import await_completed_upload

    try:
        model_bytes = await await_completed_upload(upload_id)
    except (OSError, RuntimeError):
        _notify_rejected(['Model upload failed. Check the logs.'])
        return

    stem = _model_stem(filename, label)
    # Reject a duplicate stem: overwriting in place wouldn't change the model pool,
    # so the engine would keep the old loaded model until restart. Make the user
    # delete the existing one first (which prunes its trigger and forces a reload).
    if stem in scan_models():
        _notify_rejected(
            [
                f'A model named "{stem}" already exists. Delete it first '
                '(Engines → OpenWakeWord → Models) or rename your upload.',
            ],
        )
        return

    # OpenWakeWord can't load *any* custom model without the shared feature-extractor
    # helpers (melspectrogram/embedding). Without them the upload would import as
    # "available" yet detection would silently never fire (the engine load raises and
    # drops audio). Block until a default model — which fetches the helpers — exists.
    if not helpers_available():
        _notify_setup_required(
            'Download a default OpenWakeWord model first (Engines → OpenWakeWord → '
            'Models). Custom models need its shared helper files before they can run.',
        )
        return

    # Reject files that aren't OpenWakeWord-compatible (real Model load + a smoke
    # prediction) before writing, so the Models list never offers a dud.
    if not await asyncio.to_thread(validate_openwakeword_model, model_bytes):
        _notify_rejected(["That file isn't a valid OpenWakeWord .onnx model."])
        return

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    # The ONNX payload can be several MB — write it off the loop.
    await asyncio.to_thread((MODELS_DIR / f'{stem}.onnx').write_bytes, model_bytes)
    store.dispatch(
        WakeWordSetAvailableModelsAction(engine=engine, models=tuple(scan_models())),
    )


# Menu ids for the mode-first tree.
_MENU_WAKE_UP = 'speech-recognition:wake-up'
_MENU_PHRASES = 'speech-recognition:wake-phrases'
_MENU_ENGINES = 'speech-recognition:wake-engines'


def _menu_mode(mode: WakeMode) -> str:
    return f'speech-recognition:wake-mode:{mode.value}'


def _menu_engine(engine: WakeWordEngineName) -> str:
    return f'speech-recognition:wake-engine:{engine.value}'


def _oww_config(
    wake_engines: tuple[WakeWordEngineConfig, ...],
) -> WakeWordEngineConfig | None:
    return next(
        (c for c in wake_engines if c.engine is WakeWordEngineName.OPENWAKEWORD),
        None,
    )


def dispatch_wake_menus(
    wake_engines: tuple[WakeWordEngineConfig, ...],
    openwakeword_models: tuple[str, ...],
    models_status: dict[WakeWordEngineName, WakeWordModelStatus],
    ir_devices: list[InfraredDevice],
) -> None:
    """(Re)build the whole mode-first wake-up menu tree from state."""
    _dispatch_wake_up_menu()
    _dispatch_phrases_menu()
    for mode in _WAKE_MODE_META:
        _dispatch_mode_menu(mode, wake_engines, ir_devices)
    _dispatch_engines_menu(wake_engines)
    config = _oww_config(wake_engines)
    if config is not None:
        _dispatch_engine_menu(config, openwakeword_models, models_status)
        _dispatch_oww_models_menu(
            openwakeword_models,
            downloading=models_status.get(WakeWordEngineName.OPENWAKEWORD)
            is WakeWordModelStatus.DOWNLOADING,
        )


def _dispatch_wake_up_menu() -> None:
    rows = (
        MenuItemData(
            key='phrases',
            label='Phrases',
            icon='\U000f036f',
            action_id=f'speech-recognition:goto:{_MENU_PHRASES}',
        ),
        MenuItemData(
            key='engines',
            label='Engines',
            icon='\U000f02ca',
            action_id=f'speech-recognition:goto:{_MENU_ENGINES}',
        ),
    )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=_MENU_WAKE_UP,
            title='Wake Up',
            heading='Wake Up',
            sub_heading='Manage what wakes the assistant.',
            items=rows,
            placeholder='',
        ),
    )


def _dispatch_phrases_menu() -> None:
    rows = tuple(
        MenuItemData(
            key=mode.value,
            label=_WAKE_MODE_META[mode][0],
            icon='\U000f036f',
            action_id=f'speech-recognition:goto:{_menu_mode(mode)}',
        )
        for mode in _PHRASE_MODES
    )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=_MENU_PHRASES,
            title='Phrases',
            heading='Phrases',
            sub_heading='Phrases that start the assistant.',
            items=rows,
            placeholder='',
        ),
    )


def _dispatch_mode_menu(
    mode: WakeMode,
    wake_engines: tuple[WakeWordEngineConfig, ...],
    ir_devices: list[InfraredDevice],
) -> None:
    """Headed list of every trigger for *mode* across all sources + an Add row."""
    title, description = _WAKE_MODE_META[mode]
    rows: list[MenuItemData] = []
    for config in wake_engines:
        rows.extend(
            MenuItemData(
                key=f'trigger-{config.engine.value}-{trigger.id}',
                label=f'{trigger.label} · {_engine_label(config.engine)}',
                icon='\U000f036f',
                action_id=(
                    f'speech-recognition:open-trigger:'
                    f'{config.engine.value}:{mode.value}:{trigger.id}'
                ),
            )
            for trigger in config.triggers
            if trigger.mode is mode
        )
    mode_key = MODE_BINDABLE_KEY[mode]
    rows.extend(
        MenuItemData(
            key=f'ir-{device.protocol}-{device.scancode}',
            label=f'{device.name} · Infrared',
            icon='\U000f036f',
            action_id=(
                f'speech-recognition:open-ir:'
                f'{mode.value}:{device.protocol}:{device.scancode}'
            ),
        )
        for device in ir_devices
        if device.bound_action_key == mode_key
    )
    rows.append(
        MenuItemData(
            key='add',
            label='Add',
            icon='󰐕',
            action_id=f'speech-recognition:add-trigger:{mode.value}',
        ),
    )
    if mode is WakeMode.CONVERSATION:
        rows.append(
            MenuItemData(
                key='end-phrases',
                label=_END_PHRASES_LABEL,
                icon='\U000f036f',
                action_id='speech-recognition:edit-end-phrases',
            ),
        )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=_menu_mode(mode),
            title=title,
            heading=title,
            sub_heading=description,
            items=tuple(rows),
            placeholder='Nothing yet — tap Add.',
        ),
    )


def _dispatch_engines_menu(
    wake_engines: tuple[WakeWordEngineConfig, ...],
) -> None:
    config = _oww_config(wake_engines)
    enabled = bool(config and config.enabled)
    rows = (
        MenuItemData(
            key='openwakeword',
            label=f'OpenWakeWord ({"On" if enabled else "Off"})',
            icon='\U000f036f',
            action_id=(
                f'speech-recognition:goto:'
                f'{_menu_engine(WakeWordEngineName.OPENWAKEWORD)}'
            ),
        ),
    )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=_MENU_ENGINES,
            title='Engines',
            heading='Engines',
            sub_heading='Enable engines and manage their models.',
            items=rows,
            placeholder='',
        ),
    )


def _menu_engine_models(engine: WakeWordEngineName) -> str:
    return f'speech-recognition:wake-engine:{engine.value}:models'


def _download_or_models_row(
    engine: WakeWordEngineName,
    models: tuple[str, ...],
    *,
    downloading: bool,
) -> MenuItemData:
    """Build the "Download Models" trigger, or "Models" list link once any exist."""
    if downloading:
        return MenuItemData(
            key='download',
            label='Downloading…',
            icon='\U000f01da',
            action_id=None,
        )
    if models:
        return MenuItemData(
            key='models',
            label='Models',
            icon='\U000f01da',
            action_id=f'speech-recognition:goto:{_menu_engine_models(engine)}',
        )
    return MenuItemData(
        key='download',
        label='Download Models',
        icon='\U000f01da',
        action_id=f'speech-recognition:download-models:{engine.value}',
    )


def _dispatch_engine_menu(
    config: WakeWordEngineConfig,
    models: tuple[str, ...],
    models_status: dict[WakeWordEngineName, WakeWordModelStatus],
) -> None:
    engine = config.engine
    downloading = models_status.get(engine) is WakeWordModelStatus.DOWNLOADING
    rows: list[MenuItemData] = [
        _build_toggle_item(
            key='engine-enabled',
            label='Disable Engine' if config.enabled else 'Enable Engine',
            is_active=config.enabled,
            action_id=f'speech-recognition:toggle-engine:{engine.value}',
        ),
        _download_or_models_row(engine, models, downloading=downloading),
        MenuItemData(
            key='upload',
            label='Upload Model',
            icon='\U000f0552',
            action_id=f'speech-recognition:upload-model:{engine.value}',
        ),
    ]
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=_menu_engine(engine),
            title=_engine_label(engine),
            heading=_engine_label(engine),
            sub_heading='Enabled' if config.enabled else 'Disabled',
            items=tuple(rows),
            placeholder='',
        ),
    )


def _dispatch_oww_models_menu(
    models: tuple[str, ...],
    *,
    downloading: bool,
) -> None:
    """List the downloaded OpenWakeWord models (tap to delete) + a re-fetch row."""
    engine = WakeWordEngineName.OPENWAKEWORD
    rows: list[MenuItemData] = [
        MenuItemData(
            key=f'model-{stem}',
            label=stem,
            icon='\U000f0411',
            action_id=f'speech-recognition:delete-model:{engine.value}:{stem}',
        )
        for stem in models
    ]
    rows.append(
        MenuItemData(
            key='download',
            label='Downloading…' if downloading else 'Download Default Models',
            icon='\U000f01da',
            action_id=(
                None
                if downloading
                else f'speech-recognition:download-models:{engine.value}'
            ),
        ),
    )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=_menu_engine_models(engine),
            title='Models',
            heading='Models',
            sub_heading='Tap a model to delete it.',
            items=tuple(rows),
            placeholder='No models yet',
        ),
    )


def register_wake_handlers(  # noqa: C901, PLR0915
    engines_manager: EnginesManager,
) -> Subscriptions:
    """Register the wake-up menu handlers + the end-phrase policy mirror.

    A registration aggregator: many small one-line navigation/edit/remove
    handlers, each trivial, so the cyclomatic/statement count is incidental.
    Returns cleanup callables (action unregistration + the mirror autorun's
    unsubscribe) so the service can tear them down on restart.
    """

    def _goto(action_id: str) -> None:
        # The dynamic-menu id is carried verbatim after the prefix.
        store.dispatch(
            StackPushMenuAction(
                menu_key=action_id.removeprefix('speech-recognition:goto:'),
            ),
        )

    def _toggle_engine(action_id: str) -> None:
        engine = WakeWordEngineName(
            action_id.removeprefix('speech-recognition:toggle-engine:'),
        )
        config = engine_config(_read_speech_recognition_state(), engine)
        store.dispatch(
            WakeEngineSetEnabledAction(
                engine=engine,
                enabled=not (config.enabled if config else False),
            ),
        )

    def _add_trigger(action_id: str) -> None:
        mode = WakeMode(action_id.removeprefix('speech-recognition:add-trigger:'))
        create_task(_add_trigger_form(mode, engines_manager))

    def _open_trigger(action_id: str) -> None:
        engine_str, mode_str, trigger_id = action_id.removeprefix(
            'speech-recognition:open-trigger:',
        ).split(':', 2)
        trigger = trigger_by_id(
            _read_speech_recognition_state(),
            WakeWordEngineName(engine_str),
            trigger_id,
        )
        if trigger is None:
            return
        store.dispatch(
            StackPushPromptAction(
                title=trigger.label,
                prompt='Edit or remove this trigger?',
                icon='󰗋',
                items=(
                    MenuItemData(
                        key='edit',
                        label='Edit',
                        icon='󰏫',
                        action_id=(
                            'speech-recognition:edit-trigger:'
                            f'{engine_str}:{mode_str}:{trigger_id}'
                        ),
                    ),
                    MenuItemData(
                        key='remove',
                        label='Remove',
                        icon='󰆴',
                        action_id=(
                            'speech-recognition:remove-trigger:'
                            f'{engine_str}:{mode_str}:{trigger_id}'
                        ),
                    ),
                ),
            ),
        )

    def _edit_trigger(action_id: str) -> None:
        engine_str, mode_str, trigger_id = action_id.removeprefix(
            'speech-recognition:edit-trigger:',
        ).split(':', 2)
        engine = WakeWordEngineName(engine_str)
        trigger = trigger_by_id(
            _read_speech_recognition_state(),
            engine,
            trigger_id,
        )
        store.dispatch(StackPopAction())
        if trigger is None:
            return
        source = (
            _SOURCE_VOSK
            if engine is WakeWordEngineName.VOSK
            else _SOURCE_OPENWAKEWORD
        )
        create_task(
            _provide_value_form(
                WakeMode(mode_str),
                source,
                engines_manager,
                replace_target=trigger,
            ),
        )

    def _remove_trigger(action_id: str) -> None:
        engine_str, _mode_str, trigger_id = action_id.removeprefix(
            'speech-recognition:remove-trigger:',
        ).split(':', 2)
        store.dispatch(
            StackPopAction(),
            WakeTriggerRemoveAction(
                engine=WakeWordEngineName(engine_str),
                id=trigger_id,
            ),
        )

    def _open_ir(action_id: str) -> None:
        mode_str, protocol, scancode = action_id.removeprefix(
            'speech-recognition:open-ir:',
        ).split(':', 2)
        device = _find_ir_device(protocol, scancode)
        if device is None:
            return
        store.dispatch(
            StackPushPromptAction(
                title=device.name,
                prompt='Edit or remove this remote key?',
                icon='󰗋',
                items=(
                    MenuItemData(
                        key='edit',
                        label='Edit',
                        icon='󰏫',
                        action_id=(
                            'speech-recognition:edit-ir:'
                            f'{mode_str}:{protocol}:{scancode}'
                        ),
                    ),
                    MenuItemData(
                        key='remove',
                        label='Remove',
                        icon='󰆴',
                        action_id=(
                            'speech-recognition:remove-ir:'
                            f'{mode_str}:{protocol}:{scancode}'
                        ),
                    ),
                ),
            ),
        )

    def _edit_ir(action_id: str) -> None:
        mode_str, protocol, scancode = action_id.removeprefix(
            'speech-recognition:edit-ir:',
        ).split(':', 2)
        device = _find_ir_device(protocol, scancode)
        store.dispatch(StackPopAction())
        if device is None:
            return
        create_task(
            _provide_value_form(
                WakeMode(mode_str),
                _SOURCE_INFRARED,
                engines_manager,
                replace_target=device,
            ),
        )

    def _remove_ir(action_id: str) -> None:
        _mode_str, protocol, scancode = action_id.removeprefix(
            'speech-recognition:remove-ir:',
        ).split(':', 2)
        device = _find_ir_device(protocol, scancode)
        store.dispatch(StackPopAction())
        if device is None:
            return
        # Unbind only — the device stays registered (replay-only) in Infrared.
        store.dispatch(
            InfraredAddDeviceAction(
                name=device.name,
                protocol=device.protocol,
                scancode=device.scancode,
                description=device.description,
                bound_action_key=None,
            ),
        )

    def _download_models(action_id: str) -> None:
        engine = WakeWordEngineName(
            action_id.removeprefix('speech-recognition:download-models:'),
        )
        store.dispatch(WakeWordDownloadModelsAction(engine_name=engine))

    def _upload_model(action_id: str) -> None:
        engine = WakeWordEngineName(
            action_id.removeprefix('speech-recognition:upload-model:'),
        )
        create_task(_upload_model_form(engine))

    def _delete_model(action_id: str) -> None:
        engine_str, stem = action_id.removeprefix(
            'speech-recognition:delete-model:',
        ).split(':', 1)
        store.dispatch(
            StackPushPromptAction(
                title='Delete Model',
                prompt=f'Delete model "{stem}"?',
                icon='\U000f0411',
                items=(
                    MenuItemData(
                        key='yes',
                        label='Delete',
                        icon='\U000f0411',
                        action_id=(
                            'speech-recognition:confirm-delete-model:'
                            f'{engine_str}:{stem}'
                        ),
                    ),
                    MenuItemData(
                        key='cancel',
                        label='Cancel',
                        icon='\U000f0156',
                        action_id='speech-recognition:cancel',
                    ),
                ),
            ),
        )

    def _confirm_delete_model(action_id: str) -> None:
        engine_str, stem = action_id.removeprefix(
            'speech-recognition:confirm-delete-model:',
        ).split(':', 1)
        store.dispatch(
            StackPopAction(),
            WakeWordDeleteModelAction(
                engine=WakeWordEngineName(engine_str),
                model_id=stem,
            ),
        )

    def _cancel() -> None:
        store.dispatch(StackPopAction())

    def _edit_end_phrases() -> None:
        store.dispatch(StackPopAction())
        create_task(_end_phrases_form(engines_manager))

    action_handlers = (
        ('speech-recognition:goto:*', _goto),
        ('speech-recognition:toggle-engine:*', _toggle_engine),
        ('speech-recognition:add-trigger:*', _add_trigger),
        ('speech-recognition:open-trigger:*', _open_trigger),
        ('speech-recognition:edit-trigger:*', _edit_trigger),
        ('speech-recognition:remove-trigger:*', _remove_trigger),
        ('speech-recognition:open-ir:*', _open_ir),
        ('speech-recognition:edit-ir:*', _edit_ir),
        ('speech-recognition:remove-ir:*', _remove_ir),
        ('speech-recognition:download-models:*', _download_models),
        ('speech-recognition:upload-model:*', _upload_model),
        ('speech-recognition:delete-model:*', _delete_model),
        ('speech-recognition:confirm-delete-model:*', _confirm_delete_model),
        ('speech-recognition:cancel', _cancel),
        ('speech-recognition:edit-end-phrases', _edit_end_phrases),
    )
    for action_id, handler in action_handlers:
        register_action(action_id, handler, allow_reregister=True)

    @store.autorun(lambda state: state.speech_recognition.conversation_end_phrases)
    def _mirror_conversation_end_phrases(phrases: tuple[str, ...]) -> None:
        """Mirror editable end phrases into the assistant conversation policy.

        Fires on startup too, so a persisted custom value re-points the policy
        (whose default table is seeded from the module constant).
        """
        store.dispatch(AssistantSetConversationEndPhrasesAction(phrases=phrases))

    def _unregister(action_id: str) -> Callable[[], None]:
        def _cleanup() -> None:
            unregister_action(action_id)

        return _cleanup

    return [
        *(_unregister(action_id) for action_id, _ in action_handlers),
        _mirror_conversation_end_phrases.unsubscribe,
    ]

