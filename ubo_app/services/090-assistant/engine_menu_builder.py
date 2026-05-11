"""Generic engine menu builder for the assistant service.

Extracts the repeated pattern from the 4 engine selector autoruns (STT, LLM,
TTS, Image Generator) in ``setup.py``, each of which was ~73 lines of
near-identical code.

Each engine menu follows the same structure:
1. Watch (selected_engine, secrets_mod_time, provider_setup_status)
2. Unregister old action IDs
3. For each engine: build a MenuItemData based on selected/setup state
4. Dispatch UpdateDynamicMenuAction
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from ubo_app.colors import INFO_COLOR, WARNING_COLOR
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import MenuItemData, UpdateDynamicMenuAction
from ubo_app.store.main import store

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ubo_app.utils.menu_items import ItemParameters

_KT = TypeVar('_KT', bound=str)


def _get_selected_params(*, is_offline: bool) -> ItemParameters:
    return {
        'icon': '󰱒',
        'background_color': INFO_COLOR if is_offline else WARNING_COLOR,
        'color': '#ffffff',
    }


def _get_unselected_params(*, is_offline: bool) -> ItemParameters:
    return {
        'icon': '󰄱',
        'background_color': '#000000',
        'color': INFO_COLOR if is_offline else WARNING_COLOR,
    }


def _get_not_setup_params(*, is_offline: bool) -> ItemParameters:
    return {
        'icon': '',
        'background_color': '#000000',
        'color': INFO_COLOR if is_offline else WARNING_COLOR,
    }


def build_engine_menu(  # noqa: PLR0913
    *,
    engines: Mapping[_KT, object],
    selected_name: str,
    menu_id: str,
    title: str,
    action_prefix: str,
    select_action_factory: Callable[[str], Callable[[], None]],
    action_ids_list: list[str],
) -> None:
    """Build and dispatch a dynamic menu for an engine category.

    Args:
        engines: Mapping of engine_name → engine instance.
        selected_name: The currently selected engine name.
        menu_id: Dynamic menu ID to dispatch to.
        title: Menu title.
        action_prefix: Prefix for action IDs (e.g., 'assistant:stt').
        select_action_factory: Factory that takes engine_name and returns
            a callable that dispatches the selection action.
        action_ids_list: Mutable list to track registered action IDs
            (cleaned up before each rebuild).

    """
    # Clean up old actions
    for action_id in action_ids_list:
        unregister_action(action_id)
    action_ids_list.clear()

    items: list[MenuItemData] = []
    for engine_name, engine in engines.items():
        is_offline = not isinstance(engine, RemoteMixin)

        if isinstance(engine, NeedsSetupMixin) and not engine.is_setup:
            # Engine needs setup — show setup action
            action_id = f'assistant:setup-{action_prefix}:{engine_name}'
            action_ids_list.append(action_id)
            register_action(action_id, engine.setup, allow_reregister=True)
            params = _get_not_setup_params(is_offline=is_offline)
        else:
            # Engine is ready — show select action
            action_id = f'assistant:select-{action_prefix}:{engine_name}'
            action_ids_list.append(action_id)
            register_action(
                action_id,
                select_action_factory(engine_name),
                allow_reregister=True,
            )
            params = (
                _get_selected_params(is_offline=is_offline)
                if selected_name == engine_name
                else _get_unselected_params(is_offline=is_offline)
            )

        items.append(
            MenuItemData(
                key=engine_name,
                label=(
                    getattr(engine, 'instance_label', None)
                    or str(engine_name)
                ),
                icon=params.get('icon', ''),
                color=params.get('color', '#ffffff'),
                background_color=params.get('background_color'),
                action_id=action_id,
            ),
        )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=menu_id,
            title=title,
            heading='Select Active Engine',
            sub_heading=f'[color={INFO_COLOR}]󱓻[/color] Offline models\n'
            f'[color={WARNING_COLOR}]󱓻[/color] Online models',
            items=tuple(items),
        ),
    )
