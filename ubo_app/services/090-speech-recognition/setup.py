"""Implement `init_service` for speech recognition service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from abstraction.speech_recognition_mixin import SpeechRecognitionMixin
from constants import OFFLINE_ENGINES
from engines_manager import EnginesManager
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, Item

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.store.core.menu_item_bridge import sync_items_to_dynamic_menu
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
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    ItemParameters,
)
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Sequence

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
    ) -> Sequence[Item]:
        """Return items for recognition engine selection."""
        _, selected_engine, _ = data
        items: list[Item] = []
        for engine_name in SpeechRecognitionEngineName:
            engine = engines_manager.engines_by_name[engine_name]

            if not isinstance(engine, SpeechRecognitionMixin):
                continue

            if isinstance(engine, NeedsSetupMixin) and not engine.is_setup:
                items.append(
                    ActionItem(
                        key=engine_name,
                        label=f'Setup {engine.label}',
                        icon='\ue615',
                        action=engine.setup,
                    ),
                )
                continue

            items.append(
                UboDispatchItem(
                    key=engine_name,
                    label=engine.label,
                    store_action=SpeechRecognitionSetSelectedEngineAction(
                        engine_name=engine_name,
                    ),
                    **(
                        _get_selected_item_parameters(
                            is_offline=engine_name in OFFLINE_ENGINES,
                        )
                        if selected_engine == engine_name
                        else _get_unselected_item_parameters(
                            is_offline=engine_name in OFFLINE_ENGINES,
                        )
                    ),
                ),
            )

        sync_items_to_dynamic_menu(
            menu_id='speech-recognition:engines',
            title='Recognition Engines',
            heading='Select Active Engine',
            sub_heading=f'[color={SUCCESS_COLOR}]󱓻[/color] Offline models\n'
            f'[color={WARNING_COLOR}]󱓻[/color] Online models',
            items=items,
        )
        return items

    @store.autorun(
        lambda state: (
            state.speech_recognition.is_intents_active,
            state.speech_recognition.is_assistant_active,
        ),
    )
    def speech_recognition_items(data: tuple[bool, bool]) -> list[Item]:
        is_intents_active, is_assistant_active = data

        items: list[Item] = [
            UboDispatchItem(
                key='is_intents_active',
                label='Command Interface',
                store_action=SpeechRecognitionSetIsIntentsActiveAction(
                    is_active=not is_intents_active,
                ),
                **(
                    SELECTED_ITEM_PARAMETERS
                    if is_intents_active
                    else UNSELECTED_ITEM_PARAMETERS
                ),
            ),
            UboDispatchItem(
                key='is_assistant_active',
                label='Voice Assistant',
                store_action=SpeechRecognitionSetIsAssistantActiveAction(
                    is_active=not is_assistant_active,
                ),
                **(
                    SELECTED_ITEM_PARAMETERS
                    if is_assistant_active
                    else UNSELECTED_ITEM_PARAMETERS
                ),
            ),
        ]
        sync_items_to_dynamic_menu(
            menu_id='speech-recognition:services',
            title='Services',
            items=items,
        )
        return items

    # Register action handlers for main menu navigation
    from ubo_app.store.core.action_registry import register_action

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

    # Create the top-level speech recognition menu with two submenus
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
                    label='Recognition Engine',
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
            icon='',
        ),
    )

    # Register path matcher for Speech Recognition menu navigation
    from ubo_app.store.core.view_registry import register_path_menu_matcher

    def _speech_recognition_path_matcher(path: tuple[str, ...]) -> str | None:
        if len(path) >= 4 and path[3] == 'speech_recognition:':  # noqa: PLR2004
            if len(path) == 4:  # noqa: PLR2004
                return 'speech-recognition:main'
            if len(path) == 5:  # noqa: PLR2004
                return path[4]
        return None

    register_path_menu_matcher(
        'speech-recognition:settings',
        _speech_recognition_path_matcher,
    )

    return engines_manager.subscriptions
