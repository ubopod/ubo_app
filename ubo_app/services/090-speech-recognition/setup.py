"""Implement `init_service` for speech recognition service."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from uuid import uuid4

from abstraction.speech_recognition_mixin import SpeechRecognitionMixin
from commands import (
    COMMANDS_PERSISTENT_KEY,
    register_default_bindable_actions,
    register_shortcut_actions,
)
from constants import OFFLINE_ENGINES
from engines_manager import EnginesManager
from pattern import PatternError, expand_pattern
from redux import AutorunOptions
from wake_phrase_validation import (
    phrase_collisions,
    validate_phrase,
)

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
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
from ubo_app.store.services.assistant import AssistantSetConversationEndPhrasesAction
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
    SpeechRecognitionEngineName,
    SpeechRecognitionIntent,
    SpeechRecognitionRemoveCommandAction,
    SpeechRecognitionSetConversationEndPhrasesAction,
    SpeechRecognitionSetSelectedEngineAction,
    SpeechRecognitionSetSlotEnabledAction,
    SpeechRecognitionSetWakePhrasesAction,
    SpeechRecognitionState,
    SpeechRecognitionUpdateCommandAction,
    WakeMode,
    WakeWordSlot,
    slot_for_mode,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    ItemParameters,
)
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
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


def _get_selected_item_parameters(*, is_offline: bool) -> ItemParameters:
    return {
        **SELECTED_ITEM_PARAMETERS,
        'background_color': SUCCESS_COLOR if is_offline else WARNING_COLOR,
        'color': '#ffffff',
    }


def _get_unselected_item_parameters(*, is_offline: bool) -> ItemParameters:
    return {
        **UNSELECTED_ITEM_PARAMETERS,
        'background_color': '#000000',
        'color': SUCCESS_COLOR if is_offline else WARNING_COLOR,
    }


def _build_engine_menu_item(
    engine_name: SpeechRecognitionEngineName,
    engine: SpeechRecognitionMixin,
    *,
    selected_engine: SpeechRecognitionEngineName | None,
    action_id: str,
) -> MenuItemData:
    """Build a MenuItemData for a selectable recognition engine."""
    params = (
        _get_selected_item_parameters(is_offline=engine_name in OFFLINE_ENGINES)
        if selected_engine == engine_name
        else _get_unselected_item_parameters(is_offline=engine_name in OFFLINE_ENGINES)
    )
    return MenuItemData(
        key=engine_name,
        label=engine.label,
        icon=params.get('icon', ''),
        color=params.get('color', '#ffffff'),
        background_color=params.get('background_color'),
        action_id=action_id,
    )


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


def _register_static_menus() -> None:
    """Register static action handlers and dispatch static menus."""
    register_action(
        'speech-recognition:open_engines',
        lambda: store.dispatch(
            StackPushMenuAction(menu_key='speech-recognition:engines'),
        ),
    )
    register_action(
        'speech-recognition:open_commands',
        lambda: store.dispatch(
            StackPushMenuAction(menu_key='speech-recognition:commands'),
        ),
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id='speech-recognition:main',
            title='Speech Recognition',
            heading='Speech Recognition Settings',
            sub_heading='Vosk is used for wake word detection',
            items=(
                MenuItemData(
                    key='commands',
                    label='Commands',
                    icon='\U000f036e',
                    action_id='speech-recognition:open_commands',
                ),
                MenuItemData(
                    key='engine',
                    label='Engines',
                    icon='\uf2a2',
                    action_id='speech-recognition:open_engines',
                ),
            ),
            placeholder='',
        ),
    )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ACCESSIBILITY,
            priority=30,
            label='Speech Recognition',
            icon='\uf2a2',
        ),
        # One combined "Wake Phrases" entry under Assistant (more discoverable):
        # per-category enable/disable + multi-phrase editing. Handled here.
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            # Higher than every other Assistant entry (max is stt=50) so Wake
            # Phrases sorts first (settings entries sort by priority descending).
            priority=100,
            key='voice',
            label='Wake Phrases',
            icon='\U000f036f',
        ),
    )


# Registered-setting keys (``service:key``) → the dynamic menu id they open.
# Underscore keys map to hyphenated menu ids explicitly (no string munging).
_SETTING_KEY_TO_MENU: dict[str, str] = {
    'speech_recognition:': 'speech-recognition:main',
    'speech_recognition:voice': 'speech-recognition:voice',
}


def _speech_recognition_path_matcher(path: tuple[str, ...]) -> str | None:
    if len(path) >= 4 and path[3] in _SETTING_KEY_TO_MENU:  # noqa: PLR2004
        if len(path) == 4:  # noqa: PLR2004
            return _SETTING_KEY_TO_MENU[path[3]]
        if len(path) == 5:  # noqa: PLR2004
            return path[4]
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


def _register_command_actions() -> None:
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


# Per-mode short title + helper text (title used for menu rows + submenu heading).
_WAKE_MODE_META: dict[WakeMode, tuple[str, str]] = {
    WakeMode.INTENTS: ('Command', 'Spoken to start a voice command.'),
    WakeMode.QUICK_CHAT: ('Quick Chat', 'Spoken to start a short chat.'),
    WakeMode.CONVERSATION: ('Conversation', 'Spoken to start a long conversation.'),
    WakeMode.STOP_TALKING: ('Stop', 'Spoken to stop the assistant talking.'),
}
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


async def _wake_phrases_form(mode: WakeMode, engines_manager: EnginesManager) -> None:
    """Edit a wake/stop category's phrases (multiple alternatives, one per line).

    On rejection, dispatches a notification naming the offending words and
    returns — the user reopens the editor to fix (so the message stays visible
    instead of being hidden behind an immediately re-opened form).
    """
    model = engines_manager.wake_word_model()
    if model is None:
        _notify_blocked_no_model()
        return

    title, description = _WAKE_MODE_META[mode]
    raw = '\n'.join(slot_for_mode(_read_speech_recognition_state(), mode).phrases)
    try:
        _, result = await ubo_input(
            prompt=f'Edit {title}',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='engine',
                            label='Engine',
                            type=InputFieldType.SELECT,
                            description='OpenWakeWord and Picovoice coming soon.',
                            options=['Vosk/Kaldi'],
                            default_value='Vosk/Kaldi',
                            required=True,
                        ),
                        InputFieldDescription(
                            name='phrases',
                            label=title,
                            type=InputFieldType.LONG,
                            description=f'{description} One phrase per line.',
                            default_value=raw,
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        logger.info('Wake phrases form cancelled', extra={'mode': mode})
        return

    raw = (result.data.get('phrases', '') if result else '') or ''
    lines = _clean_phrase_lines(raw)
    state = _read_speech_recognition_state()
    problems: list[str] = []
    if not lines:
        problems.append('Enter at least one phrase.')
    for phrase in lines:
        problems += [f'"{phrase}": {p}' for p in validate_phrase(phrase, model)]
        problems += [
            f'"{phrase}": {p}' for p in phrase_collisions(phrase, mode, state)
        ]
    if problems:
        _notify_rejected(problems)
        return
    store.dispatch(
        SpeechRecognitionSetWakePhrasesAction(mode=mode, phrases=tuple(lines)),
    )


async def _end_phrases_form(engines_manager: EnginesManager) -> None:
    """Edit the conversation end phrases (multiple alternatives, one per line)."""
    model = engines_manager.wake_word_model()
    if model is None:
        _notify_blocked_no_model()
        return

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
        phrase.casefold() for slot in state.wake_slots for phrase in slot.phrases
    }
    problems: list[str] = []
    if not lines:
        problems.append('Enter at least one phrase.')
    for phrase in lines:
        problems += [f'"{phrase}": {p}' for p in validate_phrase(phrase, model)]
        if phrase in wake_values:
            problems.append(f'"{phrase}": already used by a wake phrase.')
    if problems:
        _notify_rejected(problems)
        return
    store.dispatch(
        SpeechRecognitionSetConversationEndPhrasesAction(phrases=tuple(lines)),
    )


def _slot_submenu_subheading(slot: WakeWordSlot) -> str:
    """Heading text listing a slot's phrases + enabled state (for HeadedMenu)."""
    state_line = 'Enabled' if slot.enabled else 'Disabled'
    if slot.mode in (WakeMode.CONVERSATION, WakeMode.STOP_TALKING):
        state_line += ' (Conversation and Stop turn on/off together)'
    phrases = '\n'.join(f'• {phrase}' for phrase in slot.phrases) or '• (none)'
    return f'{state_line}\n{phrases}'


def _dispatch_voice_menus(
    wake_slots: tuple[WakeWordSlot, ...],
    end_phrases: tuple[str, ...],
) -> None:
    """(Re)build the combined Wake Phrases menu + every per-category submenu."""
    rows = [
        _build_toggle_item(
            key=f'voice-{slot.mode.value}',
            label=_WAKE_MODE_META[slot.mode][0],
            is_active=slot.enabled,
            action_id=f'speech-recognition:open-slot:{slot.mode.value}',
        )
        for slot in wake_slots
    ]
    rows.append(
        MenuItemData(
            key='voice-end',
            label=_END_PHRASES_LABEL,
            icon='\U000f036f',
            action_id='speech-recognition:open-slot:end',
        ),
    )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id='speech-recognition:voice',
            title='Wake Phrases',
            heading='Wake Phrases',
            sub_heading='Enable, disable, or edit each voice trigger.',
            items=tuple(rows),
            placeholder='',
        ),
    )

    for slot in wake_slots:
        title = _WAKE_MODE_META[slot.mode][0]
        toggle_label = 'Disable' if slot.enabled else 'Enable'
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=f'speech-recognition:voice:{slot.mode.value}',
                title=title,
                heading=title,
                sub_heading=_slot_submenu_subheading(slot),
                items=(
                    _build_toggle_item(
                        key='toggle',
                        label=toggle_label,
                        is_active=slot.enabled,
                        action_id=(
                            f'speech-recognition:toggle-slot:{slot.mode.value}'
                        ),
                    ),
                    MenuItemData(
                        key='edit',
                        label='Edit Phrases',
                        icon='\U000f036f',
                        action_id=f'speech-recognition:edit-slot:{slot.mode.value}',
                    ),
                ),
                placeholder='',
            ),
        )

    end_list = '\n'.join(f'• {phrase}' for phrase in end_phrases) or '• (none)'
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id='speech-recognition:voice:end',
            title=_END_PHRASES_LABEL,
            heading=_END_PHRASES_LABEL,
            sub_heading=f'Spoken to end a conversation.\n{end_list}',
            items=(
                MenuItemData(
                    key='edit',
                    label='Edit Phrases',
                    icon='\U000f036f',
                    action_id='speech-recognition:edit-end-phrases',
                ),
            ),
            placeholder='',
        ),
    )


def _register_wake_phrase_handlers(engines_manager: EnginesManager) -> None:
    """Register open/toggle/edit handlers + the end-phrase policy mirror."""

    def _open_slot(action_id: str) -> None:
        key = action_id.removeprefix('speech-recognition:open-slot:')
        menu_key = (
            'speech-recognition:voice:end'
            if key == 'end'
            else f'speech-recognition:voice:{key}'
        )
        store.dispatch(StackPushMenuAction(menu_key=menu_key))

    def _toggle_slot(action_id: str) -> None:
        mode = WakeMode(action_id.removeprefix('speech-recognition:toggle-slot:'))
        slot = slot_for_mode(_read_speech_recognition_state(), mode)
        store.dispatch(
            SpeechRecognitionSetSlotEnabledAction(
                mode=mode,
                enabled=not slot.enabled,
            ),
        )

    def _edit_slot(action_id: str) -> None:
        mode = WakeMode(action_id.removeprefix('speech-recognition:edit-slot:'))
        # Pop the submenu so the form isn't behind it; statement (not return) so
        # no stray empty menu frame is pushed.
        store.dispatch(StackPopAction())
        create_task(_wake_phrases_form(mode, engines_manager))

    def _edit_end_phrases() -> None:
        store.dispatch(StackPopAction())
        create_task(_end_phrases_form(engines_manager))

    for action_id, handler in (
        ('speech-recognition:open-slot:*', _open_slot),
        ('speech-recognition:toggle-slot:*', _toggle_slot),
        ('speech-recognition:edit-slot:*', _edit_slot),
    ):
        register_action(action_id, handler, allow_reregister=True)
    register_action(
        'speech-recognition:edit-end-phrases',
        _edit_end_phrases,
        allow_reregister=True,
    )

    @store.autorun(lambda state: state.speech_recognition.conversation_end_phrases)
    def _mirror_conversation_end_phrases(phrases: tuple[str, ...]) -> None:
        """Mirror editable end phrases into the assistant conversation policy.

        Fires on startup too, so a persisted custom value re-points the policy
        (whose default table is seeded from the module constant).
        """
        store.dispatch(AssistantSetConversationEndPhrasesAction(phrases=phrases))


def _register_persistence() -> None:
    """Register the persistent-store keys for engine, wake slots, end phrases."""
    register_persistent_store(
        'speech_recognition:selected_engine',
        lambda state: state.speech_recognition.selected_engine or 'vosk',
    )
    register_persistent_store(
        'speech_recognition:wake_slots',
        lambda state: json.dumps(
            [
                {
                    'mode': slot.mode.value,
                    'phrases': list(slot.phrases),
                    'enabled': slot.enabled,
                }
                for slot in state.speech_recognition.wake_slots
            ],
        ),
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


def init_service() -> Subscriptions:
    """Initialize speech recognition service."""
    _register_persistence()

    register_default_bindable_actions()
    register_shortcut_actions()

    engines_manager = EnginesManager()
    _engine_action_ids: list[str] = []

    @store.autorun(
        lambda state: (
            state.speech_recognition.selected_engine,
            state.assistant.provider_setup_status,
        ),
        options=AutorunOptions(memoization=False),
    )
    def recognition_engine_items(
        data: tuple[SpeechRecognitionEngineName | None, dict[str, bool]],
    ) -> None:
        """Update items for recognition engine selection."""
        selected_engine, _ = data

        for action_id in _engine_action_ids:
            unregister_action(action_id)
        _engine_action_ids.clear()

        items: list[MenuItemData] = []
        for engine_name in SpeechRecognitionEngineName:
            engine = engines_manager.engines_by_name[engine_name]

            if not isinstance(engine, SpeechRecognitionMixin):
                continue

            if isinstance(engine, NeedsSetupMixin) and not engine.is_setup:
                action_id = f'speech-recognition:setup-engine:{engine_name}'
                _engine_action_ids.append(action_id)
                register_action(action_id, engine.setup)
                items.append(
                    MenuItemData(
                        key=engine_name,
                        label=f'Setup {engine.label}',
                        icon='\ue615',
                        action_id=action_id,
                    ),
                )
                continue

            action_id = f'speech-recognition:select-engine:{engine_name}'
            _engine_action_ids.append(action_id)
            register_action(
                action_id,
                lambda _en=engine_name: store.dispatch(
                    SpeechRecognitionSetSelectedEngineAction(engine_name=_en),
                ),
            )
            items.append(
                _build_engine_menu_item(
                    engine_name,
                    engine,
                    selected_engine=selected_engine,
                    action_id=action_id,
                ),
            )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='speech-recognition:engines',
                title='Recognition Engines',
                heading='Select Active Engine',
                sub_heading=(
                    f'[color={SUCCESS_COLOR}]󱓻[/color] Offline models\n'
                    f'[color={WARNING_COLOR}]󱓻[/color] Online models'
                ),
                items=tuple(items),
            ),
        )

    @store.autorun(
        lambda state: (
            state.speech_recognition.wake_slots,
            state.speech_recognition.conversation_end_phrases,
        ),
    )
    def voice_menu_items(
        data: tuple[tuple[WakeWordSlot, ...], tuple[str, ...]],
    ) -> None:
        """Rebuild the combined Wake Phrases menu + per-category submenus."""
        wake_slots, end_phrases = data
        _dispatch_voice_menus(wake_slots, end_phrases)

    @store.autorun(lambda state: state.speech_recognition.intents)
    def speech_recognition_command_items(
        intents: list[SpeechRecognitionIntent],
    ) -> None:
        """Update the Commands menu listing each voice command."""
        items: tuple[MenuItemData, ...] = (
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
                title='Commands',
                items=items,
                placeholder='No commands yet',
            ),
        )

    _register_wake_phrase_handlers(engines_manager)
    _register_command_actions()
    _register_static_menus()

    from ubo_app.store.core.view_registry import register_path_menu_matcher

    register_path_menu_matcher(
        'speech-recognition:settings',
        _speech_recognition_path_matcher,
    )

    return [
        *engines_manager.subscriptions,
        store.subscribe_event(
            SpeechRecognitionBoundActionTriggeredEvent,
            _handle_bound_action_triggered,
        ),
    ]
