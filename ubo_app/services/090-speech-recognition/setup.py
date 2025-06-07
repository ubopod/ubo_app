"""Implement `init_service` for speech recognition service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from abstraction.speech_recognition_mixin import SpeechRecognitionMixin
from constants import OFFLINE_ENGINES
from engines_manager import EnginesManager
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, Item, SubMenuItem

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionEngineName,
    SpeechRecognitionSetIsAssistantActiveAction,
    SpeechRecognitionSetIsIntentsActiveAction,
    SpeechRecognitionSetSelectedEngineAction,
)
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.gui import (
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
        ),
        options=AutorunOptions(memoization=False),
    )
    def recognition_engine_items(
        data: tuple[bool, SpeechRecognitionEngineName | None],
    ) -> Sequence[Item]:
        """Return items for recognition engine selection."""
        _, selected_engine = data
        items: list[Item] = []
        for engine_name in SpeechRecognitionEngineName:
            engine = engines_manager.engines_by_name[engine_name]

            if not isinstance(engine, SpeechRecognitionMixin):
                continue

            if isinstance(engine, NeedsSetupMixin) and not engine.is_setup():
                items.append(
                    ActionItem(
                        key=engine_name,
                        label=f'Setup {engine.label}',
                        icon='',
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

        return items

    @store.autorun(
        lambda state: (
            state.speech_recognition.is_intents_active,
            state.speech_recognition.is_assistant_active,
        ),
    )
    def speech_recognition_items(data: tuple[bool, bool]) -> list[Item]:
        is_intents_active, is_assistant_active = data

        return [
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

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.SPEECH,
            priority=30,
            menu_item=SubMenuItem(
                label='Speech Recognition',
                icon='',
                sub_menu=HeadedMenu(
                    title='Speech Recognition',
                    heading='Speech Recognition Settings',
                    sub_heading='Vosk is used for wake word detection',
                    items=[
                        SubMenuItem(
                            key='services',
                            label='Services',
                            icon='',
                            sub_menu=HeadlessMenu(
                                title='Services',
                                items=speech_recognition_items,
                            ),
                        ),
                        SubMenuItem(
                            key='engine',
                            label='Recognition Engine',
                            icon='',
                            sub_menu=HeadedMenu(
                                title='Recognition Engine',
                                heading='Select Active Engine',
                                sub_heading=f'[color={SUCCESS_COLOR}]󱓻[/color] Offline '
                                f'models\n[color={WARNING_COLOR}]󱓻[/color] Online '
                                'models',
                                items=recognition_engine_items,
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )

    return engines_manager.subscriptions
