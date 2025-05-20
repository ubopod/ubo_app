"""Menu items for the system menu."""

from __future__ import annotations

from ubo_gui.menu.types import HeadlessMenu, SubMenuItem

from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioInstallDriverAction
from ubo_app.store.settings.services import service_items
from ubo_app.store.settings.types import (
    SettingsToggleBetaVersionsAction,
    SettingsTogglePdbSignalAction,
    SettingsToggleVisualDebugAction,
)
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.eeprom import get_eeprom_data


@store.autorun(lambda state: state.settings.pdb_signal)
def _pdb_debug_icon(pdb_signal: bool) -> str:  # noqa: FBT001
    return '󰱒' if pdb_signal else '󰄱'


@store.autorun(lambda state: state.settings.visual_debug)
def _visual_debug_icon(visual_debug: bool) -> str:  # noqa: FBT001
    return '󰱒' if visual_debug else '󰄱'


@store.autorun(lambda state: state.settings.beta_versions)
def _beta_versions_icon(beta_versions: bool) -> str:  # noqa: FBT001
    return '󰱒' if beta_versions else '󰄱'


THIRD_PARTY_ITEMS = []

eeprom_data = get_eeprom_data()
if eeprom_data['speakers'] is not None and eeprom_data['speakers']['model'] == 'wm8960':
    THIRD_PARTY_ITEMS.append(
        UboDispatchItem(
            label='Re/Install Audio',
            store_action=AudioInstallDriverAction(),
        ),
    )

SYSTEM_MENU: list[SubMenuItem] = [
    SubMenuItem(
        key='general',
        label='General',
        icon='󰒓',
        sub_menu=HeadlessMenu(
            title='󰒓General',
            items=[
                UboDispatchItem(
                    label='PDB Signal',
                    store_action=SettingsTogglePdbSignalAction(),
                    icon=_pdb_debug_icon,
                ),
                UboDispatchItem(
                    label='Visual Debug',
                    store_action=SettingsToggleVisualDebugAction(),
                    icon=_visual_debug_icon,
                ),
                UboDispatchItem(
                    label='Beta Versions',
                    store_action=SettingsToggleBetaVersionsAction(),
                    icon=_beta_versions_icon,
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
    SubMenuItem(
        key='third_party',
        label='Third Party',
        icon='',
        sub_menu=HeadlessMenu(
            title='Third Party Tools',
            items=THIRD_PARTY_ITEMS,
        ),
    ),
]
