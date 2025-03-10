"""Menu items for the system menu."""

from __future__ import annotations

from ubo_gui.menu.types import HeadlessMenu, SubMenuItem

from ubo_app.store.dispatch_action import DispatchItem
from ubo_app.store.main import store
from ubo_app.store.settings.services import service_items
from ubo_app.store.settings.types import SettingsToggleDebugModeAction


@store.autorun(lambda state: state.settings.is_debug_enabled)
def _debug_icon(is_debug_eanbled: bool) -> str:  # noqa: FBT001
    return '󰱒' if is_debug_eanbled else '󰄱'


SYSTEM_MENU: list[SubMenuItem] = [
    SubMenuItem(
        key='general',
        label='General',
        icon='󰒓',
        sub_menu=HeadlessMenu(
            title='󰒓General',
            items=[
                DispatchItem(
                    label='Debug',
                    store_action=SettingsToggleDebugModeAction(),
                    icon=_debug_icon,
                ),
            ],
        ),
    ),
    SubMenuItem(
        key='services',
        label='Services',
        icon='',
        sub_menu=HeadlessMenu(
            title='Services',
            items=service_items,
        ),
    ),
]
