"""Implement `init_service` for speech recognition service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from abstraction.speech_recognition_mixin import SpeechRecognitionMixin
from constants import OFFLINE_ENGINES
from engines_manager import EnginesManager
from redux import AutorunOptions

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionEngineName,
    SpeechRecognitionSetIsAssistantActiveAction,
    SpeechRecognitionSetIsIntentsActiveAction,
    SpeechRecognitionSetSelectedEngineAction,
)
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    ItemParameters,
)
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


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

    _register_static_menus()

    from ubo_app.store.core.view_registry import register_path_menu_matcher

    register_path_menu_matcher(
        'speech-recognition:settings',
        _speech_recognition_path_matcher,
    )

    return engines_manager.subscriptions
