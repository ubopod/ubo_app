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
    SpeechRecognitionSetIsAssistantActiveAction,
    SpeechRecognitionSetIsIntentsActiveAction,
    SpeechRecognitionSetSelectedEngineAction,
    SpeechRecognitionUpdateCommandAction,
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
        'speech-recognition:open_services',
        lambda: store.dispatch(
            StackPushMenuAction(menu_key='speech-recognition:services'),
        ),
    )
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
                    key='services',
                    label='Services',
                    icon='\uf4a7',
                    action_id='speech-recognition:open_services',
                ),
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
    )


def _speech_recognition_path_matcher(path: tuple[str, ...]) -> str | None:
    if len(path) >= 4 and path[3] == 'speech_recognition:':  # noqa: PLR2004
        if len(path) == 4:  # noqa: PLR2004
            return 'speech-recognition:main'
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


def init_service() -> Subscriptions:
    """Initialize speech recognition service."""
    register_persistent_store(
        'speech_recognition:selected_engine',
        lambda state: state.speech_recognition.selected_engine or 'vosk',
    )
    register_persistent_store(
        'speech_recognition:is_intents_active',
        lambda state: state.speech_recognition.is_intents_active,
    )
    register_persistent_store(
        'speech_recognition:is_assistant_active',
        lambda state: state.speech_recognition.is_assistant_active,
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

    register_default_bindable_actions()
    register_shortcut_actions()

    engines_manager = EnginesManager()
    _engine_action_ids: list[str] = []
    _services_action_ids: list[str] = []

    @store.autorun(
        lambda state: (
            state.speech_recognition.is_intents_active,
            state.speech_recognition.selected_engine,
            state.assistant.provider_setup_status,
        ),
        options=AutorunOptions(memoization=False),
    )
    def recognition_engine_items(
        data: tuple[bool, SpeechRecognitionEngineName | None, dict[str, bool]],
    ) -> None:
        """Update items for recognition engine selection."""
        _, selected_engine, _ = data

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
            state.speech_recognition.is_intents_active,
            state.speech_recognition.is_assistant_active,
        ),
    )
    def speech_recognition_items(data: tuple[bool, bool]) -> None:
        """Update items for speech recognition services."""
        is_intents_active, is_assistant_active = data

        for action_id in _services_action_ids:
            unregister_action(action_id)
        _services_action_ids.clear()

        intents_action_id = 'speech-recognition:toggle-intents'
        _services_action_ids.append(intents_action_id)
        register_action(
            intents_action_id,
            lambda: store.dispatch(
                SpeechRecognitionSetIsIntentsActiveAction(
                    is_active=not is_intents_active,
                ),
            ),
        )

        assistant_action_id = 'speech-recognition:toggle-assistant'
        _services_action_ids.append(assistant_action_id)
        register_action(
            assistant_action_id,
            lambda: store.dispatch(
                SpeechRecognitionSetIsAssistantActiveAction(
                    is_active=not is_assistant_active,
                ),
            ),
        )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='speech-recognition:services',
                title='Services',
                items=(
                    _build_toggle_item(
                        key='is_intents_active',
                        label='Command Interface',
                        is_active=is_intents_active,
                        action_id=intents_action_id,
                    ),
                    _build_toggle_item(
                        key='is_assistant_active',
                        label='Voice Assistant',
                        is_active=is_assistant_active,
                        action_id=assistant_action_id,
                    ),
                ),
            ),
        )

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
