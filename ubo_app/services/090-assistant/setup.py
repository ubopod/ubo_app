"""Implement `init_service` for assistant service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from abstraction.assistant_mixin import AssistantMixin
from constants import OFFLINE_ENGINES
from engines_manager import EnginesManager
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadedMenu, Item, SubMenuItem

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantEngineName,
    AssistantSetSelectedEngineAction,
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
    """Initialize the assistant service."""
    register_persistent_store(
        'assistant:selected_engine',
        lambda state: state.assistant.selected_engine,
    )

    engines_manager = EnginesManager()

    @store.autorun(
        lambda state: (
            state.assistant.is_active,
            state.assistant.selected_engine,
        ),
        options=AutorunOptions(memoization=False),
    )
    def assistant_items(
        data: tuple[bool, AssistantEngineName | None],
    ) -> Sequence[Item]:
        """Return items for recognition engine selection."""
        _, selected_engine = data
        items: list[Item] = []
        for engine_name in AssistantEngineName:
            engine = engines_manager.engines_by_name[engine_name]

            if not isinstance(engine, AssistantMixin):
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
                    store_action=AssistantSetSelectedEngineAction(
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

    return engines_manager.subscriptions
