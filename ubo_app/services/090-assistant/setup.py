"""Implement `init_service` for assistant service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from constants import OFFLINE_ENGINES
from ollama_engine import OllamaEngine
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadedMenu, Item, SubMenuItem

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.google_cloud import GoogleEngine
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistanceAudioFrame,
    AssistantLLMName,
    AssistantReportEvent,
    AssistantSetSelectedLLMAction,
)
from ubo_app.store.services.audio import AudioPlayAudioSequenceAction
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.gui import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    ItemParameters,
)
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Sequence


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


def _communicate(event: AssistantReportEvent) -> None:
    """Communicate the assistance."""
    if isinstance(event.data, AssistanceAudioFrame):
        store.dispatch(
            AudioPlayAudioSequenceAction(
                sample=event.data.audio,
                id=f'assistant:{event.source_id}:{event.data.id}',
                index=event.data.index,
            ),
        )


async def init_service() -> None:
    """Initialize the assistant service."""
    register_persistent_store(
        'assistant:selected_llm',
        lambda state: state.assistant.selected_llm,
    )

    engines = {
        AssistantLLMName.OLLAMA: OllamaEngine(),
        AssistantLLMName.GOOGLE: GoogleEngine(name=AssistantLLMName.GOOGLE),
    }

    @store.autorun(
        lambda state: (
            state.assistant.is_active,
            state.assistant.selected_llm,
        ),
        options=AutorunOptions(memoization=False),
    )
    def assistant_items(
        data: tuple[bool, AssistantLLMName | None],
    ) -> Sequence[Item]:
        """Return items for recognition engine selection."""
        _, selected_engine = data
        items: list[Item] = []
        for llm_name in AssistantLLMName:
            if llm_name not in engines:
                continue
            engine = engines[llm_name]
            if isinstance(engine, NeedsSetupMixin) and not engine.is_setup():
                items.append(
                    ActionItem(
                        key=llm_name,
                        label=f'Setup {engine.label}',
                        icon='',
                        action=engine.setup,
                    ),
                )
                continue

            items.append(
                UboDispatchItem(
                    key=llm_name,
                    label=engine.label,
                    store_action=AssistantSetSelectedLLMAction(llm_name=llm_name),
                    **(
                        _get_selected_item_parameters(
                            is_offline=llm_name in OFFLINE_ENGINES,
                        )
                        if selected_engine == llm_name
                        else _get_unselected_item_parameters(
                            is_offline=llm_name in OFFLINE_ENGINES,
                        )
                    ),
                ),
            )

        return items

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.SPEECH,
            priority=20,
            menu_item=SubMenuItem(
                label='Assistant',
                icon='󰁤',
                sub_menu=HeadedMenu(
                    title='󰁤 Assistant',
                    heading='Assistant Settings',
                    sub_heading='',
                    items=[
                        SubMenuItem(
                            key='engine',
                            label='Assistant Engine',
                            icon='󰁤',
                            sub_menu=HeadedMenu(
                                title='󰁤Assistant Engine',
                                heading='Select Active Engine',
                                sub_heading=f'[color={SUCCESS_COLOR}]󱓻[/color] Offline '
                                f'models\n[color={WARNING_COLOR}]󱓻[/color] Online '
                                'models',
                                items=assistant_items,
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )

    store.subscribe_event(AssistantReportEvent, _communicate)
