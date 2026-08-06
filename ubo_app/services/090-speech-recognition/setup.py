"""Implement `init_service` for speech recognition service."""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import TYPE_CHECKING
from uuid import uuid4

from commands import (
    COMMANDS_PERSISTENT_KEY,
    SEEDED_IDS_PERSISTENT_KEY,
    register_default_bindable_actions,
    register_shortcut_actions,
)
from engines_manager import EnginesManager
from microwakeword_engine import MODELS_DIR as MICRO_MODELS_DIR
from microwakeword_engine import delete_model as micro_delete_model
from microwakeword_engine import scan_models as micro_scan_models
from microwakeword_engine import staging_paths as micro_staging_paths
from microwakeword_engine import validate_model as micro_validate_model
from openwakeword_engine import (
    default_model_names,
    delete_model,
    download_model,
    scan_models,
)
from pattern import PatternError, expand_pattern
from wake_menu import dispatch_wake_menus, register_wake_handlers

from ubo_app.colors import INFO_COLOR
from ubo_app.engines.microwakeword_catalog import (
    download_urls_for as microwakeword_download_urls_for,
)
from ubo_app.engines.microwakeword_catalog import model_for as microwakeword_model_for
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.bindable_actions import (
    BindableActionContext,
    get_bindable_action,
    get_bindable_actions,
)
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPopAction,
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
    AssistantDownloadVoskModelAction,
    AssistantTriggerSourceUnion,
    WakePhraseTriggerSource,
)
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.rgb_ring import (
    RgbRingBlankAction,
    RgbRingCommandAction,
    RgbRingSequenceAction,
)
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionAddCommandAction,
    SpeechRecognitionBoundActionTriggeredEvent,
    SpeechRecognitionIntent,
    SpeechRecognitionRemoveCommandAction,
    SpeechRecognitionSetAssistantListeningAction,
    SpeechRecognitionUpdateCommandAction,
    WakeMode,
    WakeWordDeleteModelEvent,
    WakeWordDownloadModelEvent,
    WakeWordDownloadModelsEvent,
    WakeWordEngineConfig,
    WakeWordEngineName,
    WakeWordModelStatus,
    WakeWordModelStatusEntry,
    WakeWordSetAvailableModelsAction,
    WakeWordSetModelsStatusAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.download import download_file
from ubo_app.utils.input import ubo_input
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.services.infrared import InfraredDevice
    from ubo_app.utils.types import Subscriptions

# Dropdown label representing "no action selected" for optional action slots.
NO_ACTION_LABEL = 'None'
# Number of action dropdown slots offered when creating/editing a command.
COMMAND_ACTION_SLOTS = 3

# Syntax guide shown behind the (ⓘ) button next to the utterances field.
PATTERN_HELP = """Patterns expand to many spoken variations, so you don't have to \
list every phrasing.

  [a, b, c]    choose one (required)    e.g.  [create, set up] wifi
  (x)          optional word           e.g.  (please) help
  (a, b)       optional choice         e.g.  turn (it) off
  plain text   matched exactly

Groups can be combined and nested. Put one pattern per line; a plain sentence \
(no brackets) still works as-is.

Example:
  [create, set up] [wifi, wireless] (connection) [via, using] [web, web ui]

matches "create wifi via web", "set up wireless connection using web ui", and \
many more."""


@store.with_state(lambda state: state.assistant.selected_vosk_model)
def _download_vosk_model(selected_vosk_model: str) -> None:
    """Start downloading the active (or default) Vosk model in place.

    Voice shortcuts only ever need Vosk, so the warning's button kicks off the
    download directly \u2014 surfacing the assistant's Vosk download progress
    notification \u2014 instead of deep-linking into Assistant \u25b8 Speech Recognition
    and making the user pick the model themselves.
    """
    store.dispatch(
        AssistantDownloadVoskModelAction(
            model_id=selected_vosk_model or DEFAULT_VOSK_MODEL_ID,
        ),
    )


def _unregister(action_id: str) -> Callable[[], None]:
    """Return a None-returning cleanup that unregisters *action_id*."""

    def _cleanup() -> None:
        unregister_action(action_id)

    return _cleanup


def _register_static_menus() -> Subscriptions:
    """Register static action handlers and dispatch static menus."""
    register_action(
        'speech-recognition:download-vosk',
        _download_vosk_model,
    )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ACCESSIBILITY,
            priority=30,
            label='Voice Shortcuts',
            icon='\U000f036e',
        ),
        # One "Wake Up" entry under Assistant: per-mode trigger phrases/models/IR
        # codes (under Phrases + Silence) and engine lifecycle (under Engines).
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            # Higher than every other Assistant entry (max is stt=50) so it sorts
            # first (settings entries sort by priority descending).
            priority=100,
            key='wake_up',
            label='Wake Up',
            icon='\U000f036f',
        ),
    )

    return [_unregister('speech-recognition:download-vosk')]


# Registered-setting keys (``service:key``) → the dynamic menu id they open.
# Underscore keys map to hyphenated menu ids explicitly (no string munging).
_SETTING_KEY_TO_MENU: dict[str, str] = {
    # The Accessibility "Voice Shortcuts" entry opens the commands menu directly
    # (the old intermediate 'speech-recognition:main' menu is gone).
    'speech_recognition:': 'speech-recognition:commands',
    'speech_recognition:wake_up': 'speech-recognition:wake-up',
}


def _speech_recognition_path_matcher(path: tuple[str, ...]) -> str | None:
    if len(path) >= 4 and path[3] in _SETTING_KEY_TO_MENU:  # noqa: PLR2004
        if len(path) == 4:  # noqa: PLR2004
            return _SETTING_KEY_TO_MENU[path[3]]
        # Deeper levels (Phrases → <mode>, Engines → <engine>, …) are pushed by
        # explicit menu_key; the dynamic-menu id always equals the trailing key.
        return path[-1]
    return None


def _handle_bound_action_triggered(
    event: SpeechRecognitionBoundActionTriggeredEvent,
) -> None:
    """Resolve a recognised command's action keys and dispatch them.

    Mirrors the infrared bound-action handler: the reducer stays pure and emits
    the event; this handler resolves each key against the bindable-actions
    registry and dispatches the produced actions, owning the acknowledgment
    sequence (an RGB blank followed by any RGB ring actions, then the rest).
    """
    # Voice commands carry no meaningful trigger source (placeholder context).
    context = BindableActionContext(protocol='', scancode='', device_name=event.phrase)
    rgb_ring_actions: list[RgbRingCommandAction] = []
    other_actions = []
    for key in event.action_keys:
        bindable = get_bindable_action(key)
        if bindable is None:
            logger.warning(
                'No bindable action registered for key',
                extra={'action_key': key},
            )
            continue
        try:
            resolved = bindable.factory(context)
        except Exception:
            logger.exception(
                'Bindable action factory failed',
                extra={'action_key': key},
            )
            continue
        if isinstance(resolved, RgbRingCommandAction):
            rgb_ring_actions.append(resolved)
        else:
            other_actions.append(resolved)

    store.dispatch(
        RgbRingSequenceAction(sequence=[RgbRingBlankAction(), *rgb_ring_actions]),
    )
    for action in other_actions:
        store.dispatch(action)


@store.with_state(lambda state: state.speech_recognition.intents)
def _find_intent(
    intents: list[SpeechRecognitionIntent],
    intent_id: str,
) -> SpeechRecognitionIntent | None:
    """Return the command with *intent_id*, or None."""
    return next((intent for intent in intents if intent.id == intent_id), None)


def _normalize_phrases(raw: str) -> list[str]:
    """Strip, drop blanks/dupes, and drop unparseable patterns.

    Lines are stored as compact patterns (see ``pattern.expand_pattern``); a
    line that doesn't parse or expands beyond the cap is logged and skipped so
    one bad line doesn't reject the whole command.
    """
    seen: set[str] = set()
    phrases: list[str] = []
    for line in raw.splitlines():
        phrase = line.strip()
        if not phrase or phrase.casefold() in seen:
            continue
        try:
            expand_pattern(phrase)
        except PatternError:
            logger.warning(
                'Skipping invalid utterance pattern',
                extra={'pattern': phrase},
            )
            continue
        seen.add(phrase.casefold())
        phrases.append(phrase)
    return phrases


def _collect_action_keys(
    data: dict[str, str],
    label_to_key: dict[str, str],
) -> list[str]:
    """Map selected slot labels back to keys, dropping None/unknown/duplicates."""
    keys: list[str] = []
    for slot in range(1, COMMAND_ACTION_SLOTS + 1):
        label = data.get(f'action_{slot}', NO_ACTION_LABEL)
        if not label or label == NO_ACTION_LABEL:
            continue
        key = label_to_key.get(label)
        if key is None:
            logger.warning('Unknown action label selected', extra={'label': label})
            continue
        if key not in keys:
            keys.append(key)
    return keys


async def _command_form(existing: SpeechRecognitionIntent | None) -> None:
    """Add or edit a voice command via a Web UI form."""
    bindables = get_bindable_actions()
    label_to_key = {bindable.label: bindable.key for bindable in bindables}
    key_to_label = {bindable.key: bindable.label for bindable in bindables}
    action_options = [NO_ACTION_LABEL, *label_to_key]

    existing_labels = (
        [
            key_to_label[key]
            for key in existing.action_keys
            if key in key_to_label
        ]
        if existing
        else []
    )

    fields = [
        InputFieldDescription(
            name='label',
            label='Name',
            type=InputFieldType.TEXT,
            description='A short name for this command',
            default_value=existing.label if existing else None,
            required=True,
        ),
        InputFieldDescription(
            name='phrases',
            label='Example Utterances',
            type=InputFieldType.LONG,
            description='One pattern per line — e.g. [turn on, switch on] lights. '
            'Tap the ⓘ for syntax.',
            help=PATTERN_HELP,
            default_value='\n'.join(existing.phrases) if existing else None,
            required=True,
        ),
        *[
            InputFieldDescription(
                name=f'action_{slot}',
                label=f'Action {slot}',
                type=InputFieldType.SELECT,
                description='Action to run when an utterance is recognised'
                if slot == 1
                else 'Optional additional action',
                options=action_options,
                default_value=(
                    existing_labels[slot - 1]
                    if slot - 1 < len(existing_labels)
                    else NO_ACTION_LABEL
                ),
                required=slot == 1,
            )
            for slot in range(1, COMMAND_ACTION_SLOTS + 1)
        ],
    ]

    try:
        _, result = await ubo_input(
            prompt='Edit voice command'
            if existing
            else 'Create a voice command',
            descriptions=[WebUIInputDescription(fields=fields)],
        )
    except asyncio.CancelledError:
        logger.info('Voice command form cancelled')
        return

    data = result.data if result else {}
    label = (data.get('label', '') or '').strip()
    phrases = _normalize_phrases(data.get('phrases', '') or '')
    action_keys = _collect_action_keys(dict(data), label_to_key)

    if not label or not phrases or not action_keys:
        logger.warning(
            'Voice command incomplete; not saving',
            extra={
                'has_label': bool(label),
                'phrase_count': len(phrases),
                'action_count': len(action_keys),
            },
        )
        return

    if existing:
        store.dispatch(
            SpeechRecognitionUpdateCommandAction(
                id=existing.id,
                label=label,
                phrases=phrases,
                action_keys=action_keys,
            ),
        )
    else:
        store.dispatch(
            SpeechRecognitionAddCommandAction(
                id=str(uuid4()),
                label=label,
                phrases=phrases,
                action_keys=action_keys,
            ),
        )


def _register_command_actions() -> Subscriptions:
    """Register the add/open/edit/remove action handlers for commands."""

    def _add_command() -> None:
        # Must return None: a non-None action-handler result makes the core
        # push an (empty) menu frame keyed by the item, leaving a stray
        # "Add Command" page behind the input form. ``create_task`` returns a
        # Task, so call it as a statement rather than returning it.
        create_task(_command_form(None))

    register_action(
        'speech-recognition:add-command',
        _add_command,
        allow_reregister=True,
    )

    def _open_command(action_id: str) -> None:
        intent_id = action_id.removeprefix('speech-recognition:open-command:')
        intent = _find_intent(intent_id)
        if intent is None:
            return
        # A prompt is a two-option widget on the GUI client (the bottom two
        # buttons; Back cancels). Keep it to exactly two items — Edit / Remove —
        # so the rendered buttons line up with the core's item indices. A third
        # item would shift the mapping and mis-fire (Edit -> Remove).
        store.dispatch(
            StackPushPromptAction(
                title=intent.label,
                prompt='Edit or remove this command?',
                icon='󰗋',
                items=(
                    MenuItemData(
                        key='edit',
                        label='Edit',
                        icon='󰏫',
                        action_id=f'speech-recognition:edit-command:{intent.id}',
                    ),
                    MenuItemData(
                        key='remove',
                        label='Remove',
                        icon='󰆴',
                        action_id=(
                            f'speech-recognition:remove-command:{intent.id}'
                        ),
                    ),
                ),
            ),
        )

    def _edit_command(action_id: str) -> None:
        intent_id = action_id.removeprefix('speech-recognition:edit-command:')
        intent = _find_intent(intent_id)
        if intent is None:
            return
        store.dispatch(StackPopAction())
        create_task(_command_form(intent))

    def _remove_command(action_id: str) -> None:
        intent_id = action_id.removeprefix('speech-recognition:remove-command:')
        store.dispatch(StackPopAction())
        store.dispatch(SpeechRecognitionRemoveCommandAction(id=intent_id))

    register_action(
        'speech-recognition:open-command:*',
        _open_command,
        allow_reregister=True,
    )
    register_action(
        'speech-recognition:edit-command:*',
        _edit_command,
        allow_reregister=True,
    )
    register_action(
        'speech-recognition:remove-command:*',
        _remove_command,
        allow_reregister=True,
    )

    return [
        _unregister('speech-recognition:add-command'),
        _unregister('speech-recognition:open-command:*'),
        _unregister('speech-recognition:edit-command:*'),
        _unregister('speech-recognition:remove-command:*'),
    ]



def _register_persistence() -> None:
    """Register the persistent-store keys for wake engines, end phrases, commands."""
    register_persistent_store(
        'speech_recognition:wake_engines',
        lambda state: json.dumps(
            [
                {
                    'engine': config.engine.value,
                    'enabled': config.enabled,
                    'triggers': [
                        {
                            'id': trigger.id,
                            'label': trigger.label,
                            'mode': trigger.mode.value,
                            'value': trigger.value,
                            'sensitivity': trigger.sensitivity,
                        }
                        for trigger in config.triggers
                    ],
                }
                for config in state.speech_recognition.wake_engines
            ],
        ),
    )
    register_persistent_store(
        'speech_recognition:enabled_wake_modes',
        lambda state: [
            mode.value for mode in state.speech_recognition.enabled_wake_modes
        ],
    )
    register_persistent_store(
        'speech_recognition:conversation_end_phrases',
        lambda state: list(state.speech_recognition.conversation_end_phrases),
    )
    register_persistent_store(
        COMMANDS_PERSISTENT_KEY,
        lambda state: json.dumps(
            [
                {
                    'id': command.id,
                    'label': command.label,
                    'phrases': command.phrases,
                    'action_keys': command.action_keys,
                }
                for command in state.speech_recognition.intents
            ],
        ),
    )
    register_persistent_store(
        SEEDED_IDS_PERSISTENT_KEY,
        lambda state: list(state.speech_recognition.seeded_default_ids),
    )


# Stable id so each progress update replaces (not stacks) the same notification.
_DOWNLOAD_NOTIFICATION_ID = 'speech_recognition:openwakeword-download'


def _download_progress_notification(
    *,
    model: str,
    done: int,
    total: int,
) -> Notification:
    """Build a sticky radial-progress notification naming the current model."""
    return Notification(
        id=_DOWNLOAD_NOTIFICATION_ID,
        title='Downloading wake-word models',
        content=f'{model}  ({done}/{total})',
        display_type=NotificationDisplayType.STICKY,
        color=INFO_COLOR,
        icon='󰇚',
        blink=False,
        progress=done / total if total else None,
        show_dismiss_action=False,
        dismiss_on_close=False,
    )


async def _handle_download_models(event: WakeWordDownloadModelsEvent) -> None:
    """Download the default models one at a time with a live progress notice.

    The reducer already marked the engine ``DOWNLOADING`` and emitted this event.
    Each default wake word is fetched off the loop and steps a radial-progress
    notification by one unit; the on-disk pool is reported after each so the
    Models list fills in live. On completion the spinner flashes "ready".
    """
    if event.engine_name != WakeWordEngineName.OPENWAKEWORD:
        logger.warning(
            'Model download not supported for engine',
            extra={'engine_name': event.engine_name},
        )
        store.dispatch(
            WakeWordSetModelsStatusAction(
                engine_name=event.engine_name,
                status=WakeWordModelStatus.NOT_AVAILABLE,
            ),
        )
        return

    names = default_model_names()
    total = len(names)
    if total == 0:
        store.dispatch(
            WakeWordSetModelsStatusAction(
                engine_name=event.engine_name,
                status=WakeWordModelStatus.ERROR,
            ),
            NotificationsAddAction(
                notification=Notification(
                    id='speech_recognition:openwakeword-download-failed',
                    title='OpenWakeWord',
                    content='OpenWakeWord is not installed. Check the logs.',
                    importance=Importance.HIGH,
                    display_type=NotificationDisplayType.FLASH,
                    icon='',
                ),
            ),
        )
        return

    for index, name in enumerate(names):
        store.dispatch(
            NotificationsAddAction(
                notification=_download_progress_notification(
                    model=name,
                    done=index,
                    total=total,
                ),
            ),
        )
        try:
            await asyncio.to_thread(download_model, name)
        except (ImportError, RuntimeError):
            logger.exception('Failed to download OpenWakeWord model')
            store.dispatch(
                WakeWordSetModelsStatusAction(
                    engine_name=event.engine_name,
                    status=WakeWordModelStatus.ERROR,
                ),
                NotificationsAddAction(
                    notification=Notification(
                        id=_DOWNLOAD_NOTIFICATION_ID,
                        title='OpenWakeWord',
                        content=f'Failed to download "{name}". Check the logs.',
                        importance=Importance.HIGH,
                        display_type=NotificationDisplayType.FLASH,
                        icon='',
                    ),
                ),
            )
            return
        # Report the growing pool after each model so the Models list updates live.
        store.dispatch(
            WakeWordSetAvailableModelsAction(
                engine=event.engine_name,
                models=tuple(scan_models()),
            ),
        )

    store.dispatch(
        WakeWordSetModelsStatusAction(
            engine_name=event.engine_name,
            status=WakeWordModelStatus.AVAILABLE,
        ),
        NotificationsAddAction(
            notification=Notification(
                id=_DOWNLOAD_NOTIFICATION_ID,
                title='Wake-word models',
                content=f'{total} models ready',
                display_type=NotificationDisplayType.FLASH,
                flash_time=2,
                color=INFO_COLOR,
                icon='󰄬',
                progress=1.0,
                show_dismiss_action=True,
                dismiss_on_close=True,
            ),
        ),
    )


# Stable id, like ``_DOWNLOAD_NOTIFICATION_ID`` — one live notification per
# microWakeWord download, replaced in place as it progresses.
_MICRO_DOWNLOAD_NOTIFICATION_ID = 'speech_recognition:microwakeword-download'


def _micro_download_failed(model_id: str, reason: str) -> None:
    """Report a failed microWakeWord download and clear the downloading status."""
    store.dispatch(
        WakeWordSetModelsStatusAction(
            engine_name=WakeWordEngineName.MICROWAKEWORD,
            status=WakeWordModelStatus.ERROR,
        ),
        NotificationsAddAction(
            notification=Notification(
                id=_MICRO_DOWNLOAD_NOTIFICATION_ID,
                title='microWakeWord',
                content=f'Failed to download "{model_id}": {reason}',
                importance=Importance.HIGH,
                display_type=NotificationDisplayType.FLASH,
                icon='',
            ),
        ),
    )


async def _handle_download_model(event: WakeWordDownloadModelEvent) -> None:
    """Download one catalog model (its ``.json`` + ``.tflite``) with a progress notice.

    The reducer already validated ``model_id`` against the catalog, marked the
    engine ``DOWNLOADING`` and emitted this event. Both halves land in a hidden
    staging directory and are only moved into place together, so a failure
    midway can never leave a half-installed model that
    :func:`micro_scan_models` would list.

    They're staged under their *final* names rather than as ``<name>.part``
    siblings because ``from_config`` resolves the weights from the manifest's
    ``model`` key relative to the manifest's own directory — a ``.part``
    manifest would send validation looking for a ``.tflite`` that isn't there
    yet, failing every download. ``micro_scan_models`` globs the top level
    only, so the staging directory stays invisible while in flight.
    """
    if event.engine != WakeWordEngineName.MICROWAKEWORD:
        logger.warning(
            'Per-model download not supported for engine',
            extra={'engine': event.engine},
        )
        store.dispatch(
            WakeWordSetModelsStatusAction(
                engine_name=event.engine,
                status=WakeWordModelStatus.NOT_AVAILABLE,
            ),
        )
        return

    model = microwakeword_model_for(event.model_id)
    if model is None:
        # Belt-and-braces: the reducer rejects unknown ids, so this only fires
        # if the catalog changed under a queued event.
        _micro_download_failed(event.model_id, 'unknown model')
        return

    json_url, tflite_url = microwakeword_download_urls_for(model.id)
    staging = micro_staging_paths(model.id)
    shutil.rmtree(staging.directory, ignore_errors=True)
    staging.directory.mkdir(parents=True, exist_ok=True)

    def _notify(progress: float) -> None:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=_MICRO_DOWNLOAD_NOTIFICATION_ID,
                    title='Downloading wake word',
                    content=model.label,
                    display_type=NotificationDisplayType.STICKY,
                    color=INFO_COLOR,
                    icon='󰇚',
                    blink=False,
                    progress=progress,
                    show_dismiss_action=False,
                    dismiss_on_close=False,
                ),
            ),
        )

    _notify(0.0)
    try:
        # The manifest is well under 1 KB against ~60 KB of weights, so the
        # progress bar tracks the ``.tflite`` alone rather than interleaving two
        # streams for a fraction of a percent.
        async for _ in download_file(url=json_url, path=staging.config):
            pass
        async for downloaded, total in download_file(
            url=tflite_url,
            path=staging.weights,
        ):
            _notify(downloaded / total if total else 0.0)
    except Exception as error:
        logger.exception(
            'Failed to download microWakeWord model',
            extra={'model': model.id},
        )
        shutil.rmtree(staging.directory, ignore_errors=True)
        _micro_download_failed(model.id, str(error) or 'download error')
        return

    if not await asyncio.to_thread(micro_validate_model, staging.config):
        shutil.rmtree(staging.directory, ignore_errors=True)
        _micro_download_failed(model.id, 'the downloaded model is not loadable')
        return

    # Weights before manifest — see `install_uploaded_model` for why the order
    # matters (`set_triggers` keys its reload signature on the `.json` alone).
    staging.weights.replace(MICRO_MODELS_DIR / f'{model.id}.tflite')
    staging.config.replace(MICRO_MODELS_DIR / f'{model.id}.json')
    shutil.rmtree(staging.directory, ignore_errors=True)

    store.dispatch(
        WakeWordSetAvailableModelsAction(
            engine=event.engine,
            models=tuple(micro_scan_models()),
        ),
        WakeWordSetModelsStatusAction(
            engine_name=event.engine,
            status=WakeWordModelStatus.AVAILABLE,
        ),
        NotificationsAddAction(
            notification=Notification(
                id=_MICRO_DOWNLOAD_NOTIFICATION_ID,
                title='Wake word ready',
                content=model.label,
                display_type=NotificationDisplayType.FLASH,
                flash_time=2,
                color=INFO_COLOR,
                icon='󰄬',
                progress=1.0,
                show_dismiss_action=True,
                dismiss_on_close=True,
            ),
        ),
    )


async def _handle_delete_model(event: WakeWordDeleteModelEvent) -> None:
    """Delete a wake-word model file off-reducer and re-scan the pool."""
    if event.engine == WakeWordEngineName.OPENWAKEWORD:
        await asyncio.to_thread(delete_model, event.model_id)
        models = tuple(scan_models())
    elif event.engine == WakeWordEngineName.MICROWAKEWORD:
        await asyncio.to_thread(micro_delete_model, event.model_id)
        models = tuple(micro_scan_models())
    else:
        return
    store.dispatch(
        WakeWordSetAvailableModelsAction(engine=event.engine, models=models),
    )


def init_service() -> Subscriptions:
    """Initialize speech recognition service."""
    _register_persistence()

    register_default_bindable_actions()
    register_shortcut_actions()

    engines_manager = EnginesManager()

    @store.autorun(
        lambda state: (
            state.speech_recognition.wake_engines,
            state.speech_recognition.enabled_wake_modes,
            state.speech_recognition.openwakeword_models,
            state.speech_recognition.microwakeword_models,
            state.speech_recognition.wake_word_models_status,
            state.infrared.registered_devices,
        ),
    )
    def wake_menu_items(
        data: tuple[
            tuple[WakeWordEngineConfig, ...],
            tuple[WakeMode, ...],
            tuple[str, ...],
            tuple[str, ...],
            tuple[WakeWordModelStatusEntry, ...],
            list[InfraredDevice],
        ],
    ) -> None:
        """Rebuild the mode-first wake-up menu tree from speech + infrared state."""
        (
            wake_engines,
            enabled_wake_modes,
            openwakeword_models,
            microwakeword_models,
            status_entries,
            ir_devices,
        ) = data
        dispatch_wake_menus(
            wake_engines,
            enabled_wake_modes,
            {
                WakeWordEngineName.OPENWAKEWORD: openwakeword_models,
                WakeWordEngineName.MICROWAKEWORD: microwakeword_models,
            },
            status_entries,
            list(ir_devices),
        )

    @store.autorun(
        lambda state: (
            state.speech_recognition.intents,
            state.assistant.selected_vosk_model,
            state.assistant.vosk_downloaded_models,
        ),
    )
    def speech_recognition_command_items(
        data: tuple[list[SpeechRecognitionIntent], str, tuple[str, ...]],
    ) -> None:
        """Update the Voice Shortcuts menu listing each voice command.

        The menu is headed so it can warn when the Vosk model — required for
        wake-word and command recognition — hasn't been downloaded. When it's
        missing, a "Download Vosk" item starts the download in place (voice
        shortcuts only ever need Vosk, so there's no model to pick).
        """
        intents, selected_vosk_model, downloaded_models = data
        model_ready = (
            selected_vosk_model or DEFAULT_VOSK_MODEL_ID
        ) in downloaded_models

        download_item: tuple[MenuItemData, ...] = (
            ()
            if model_ready
            else (
                MenuItemData(
                    key='download-model',
                    label='Download Vosk',
                    icon='󰇚',
                    action_id='speech-recognition:download-vosk',
                ),
            )
        )
        items: tuple[MenuItemData, ...] = (
            *download_item,
            MenuItemData(
                key='add-command',
                label='Add Command',
                icon='󰐕',
                action_id='speech-recognition:add-command',
            ),
            *(
                MenuItemData(
                    key=f'command-{intent.id}',
                    label=intent.label,
                    icon='󰗋',
                    action_id=f'speech-recognition:open-command:{intent.id}',
                )
                for intent in intents
            ),
        )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='speech-recognition:commands',
                title='Voice Shortcuts',
                heading='Voice Shortcuts',
                sub_heading=(
                    'Speak a phrase after the wake word to run a shortcut.'
                    if model_ready
                    else 'Voice shortcuts need the Vosk model — press '
                    'Download Vosk to get it.'
                ),
                items=items,
                placeholder='No commands yet',
            ),
        )

    wake_handler_cleanups = register_wake_handlers(engines_manager)
    command_action_cleanups = _register_command_actions()
    static_menu_cleanups = _register_static_menus()

    # Seed each engine's model pool + status from disk so the Manage Models tab
    # renders. Done here (service start), never in the reducer, to keep the
    # reducer free of filesystem I/O.
    available_models = tuple(scan_models())
    available_micro_models = tuple(micro_scan_models())
    store.dispatch(
        WakeWordSetAvailableModelsAction(
            engine=WakeWordEngineName.OPENWAKEWORD,
            models=available_models,
        ),
        WakeWordSetModelsStatusAction(
            engine_name=WakeWordEngineName.OPENWAKEWORD,
            status=WakeWordModelStatus.AVAILABLE
            if available_models
            else WakeWordModelStatus.NOT_AVAILABLE,
        ),
        WakeWordSetAvailableModelsAction(
            engine=WakeWordEngineName.MICROWAKEWORD,
            models=available_micro_models,
        ),
        WakeWordSetModelsStatusAction(
            engine_name=WakeWordEngineName.MICROWAKEWORD,
            status=WakeWordModelStatus.AVAILABLE
            if available_micro_models
            else WakeWordModelStatus.NOT_AVAILABLE,
        ),
    )

    @store.autorun(
        lambda state: (
            state.assistant.is_listening,
            state.assistant.active_source,
            state.assistant.active_audio_source,
        ),
    )
    def assistant_listening_arming(
        data: tuple[bool, AssistantTriggerSourceUnion | None, str],
    ) -> None:
        """Arm stage-1 command matching for the life of a quick-chat session.

        Only wake-phrase QUICK_CHAT sessions arm it — those are the ones the user
        expects to answer a shortcut. Keying the disarm off ``is_listening`` covers
        every stop path at once (silence flush, end phrase, stop-talking, toggle,
        bot speech, a swallowed wake while the mic is muted).
        """
        is_listening, active_source, active_audio_source = data
        is_quick_chat = (
            is_listening
            and isinstance(active_source, WakePhraseTriggerSource)
            and active_source.mode == WakeMode.QUICK_CHAT
        )
        store.dispatch(
            SpeechRecognitionSetAssistantListeningAction(
                active=is_quick_chat,
                audio_source=active_audio_source if is_quick_chat else '',
            ),
        )

    from ubo_app.store.core.view_registry import register_path_menu_matcher

    unregister_path_matcher = register_path_menu_matcher(
        'speech-recognition:settings',
        _speech_recognition_path_matcher,
    )

    return [
        *engines_manager.subscriptions,
        assistant_listening_arming.unsubscribe,
        *wake_handler_cleanups,
        *command_action_cleanups,
        *static_menu_cleanups,
        wake_menu_items.unsubscribe,
        speech_recognition_command_items.unsubscribe,
        unregister_path_matcher,
        store.subscribe_event(
            SpeechRecognitionBoundActionTriggeredEvent,
            _handle_bound_action_triggered,
        ),
        store.subscribe_event(
            WakeWordDownloadModelsEvent,
            _handle_download_models,
        ),
        store.subscribe_event(
            WakeWordDownloadModelEvent,
            _handle_download_model,
        ),
        store.subscribe_event(
            WakeWordDeleteModelEvent,
            _handle_delete_model,
        ),
    ]
