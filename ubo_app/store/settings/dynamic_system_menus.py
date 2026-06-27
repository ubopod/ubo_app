"""Dynamic menus for System settings (General, Services, Third Party).

Replaces the static SYSTEM_MENU from settings/menu.py with dynamic menus
that update via autoruns and the action registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from redux import AutorunOptions

from ubo_app.colors import RUNNING_COLOR, STOPPED_COLOR, WARNING_COLOR
from ubo_app.store.core.constants import MENU_NAVIGATE_PREFIX
from ubo_app.store.core.types import (
    MenuItemData,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store

if TYPE_CHECKING:
    from ubo_app.store.settings.types import ServiceState

# =============================================================================
# Menu IDs
# =============================================================================
GENERAL_MENU_ID = 'settings:system:general'
SERVICES_MENU_ID = 'settings:system:services'
THIRD_PARTY_MENU_ID = 'settings:system:third_party'

# =============================================================================
# General Settings
# =============================================================================


def _setup_general_settings() -> None:
    """Set up dynamic menu and action handlers for General settings."""
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.settings.types import (
        SettingsToggleBetaVersionsAction,
        SettingsToggleGrpcRemoteAccessAction,
        SettingsTogglePdbSignalAction,
        SettingsToggleVisualDebugAction,
    )

    def _toggle_pdb() -> None:
        store.dispatch(SettingsTogglePdbSignalAction())

    def _toggle_visual_debug() -> None:
        store.dispatch(SettingsToggleVisualDebugAction())

    def _toggle_beta() -> None:
        store.dispatch(SettingsToggleBetaVersionsAction())

    def _toggle_grpc_remote_access() -> None:
        store.dispatch(SettingsToggleGrpcRemoteAccessAction())

    register_action('settings:general:toggle_pdb', _toggle_pdb)
    register_action('settings:general:toggle_visual_debug', _toggle_visual_debug)
    register_action('settings:general:toggle_beta', _toggle_beta)
    register_action(
        'settings:general:toggle_grpc_remote_access',
        _toggle_grpc_remote_access,
    )

    @store.autorun(
        lambda state: (
            state.settings.pdb_signal,
            state.settings.visual_debug,
            state.settings.beta_versions,
            state.settings.grpc_remote_access,
        ),
        options=AutorunOptions(default_value=None),
    )
    def _sync_general_menu(
        data: tuple[bool, bool, bool, bool] | None,
    ) -> None:
        if data is None:
            return
        pdb_signal, visual_debug, beta_versions, grpc_remote_access = data

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=GENERAL_MENU_ID,
                title='󰒓General',
                items=(
                    MenuItemData(
                        key='pdb_signal',
                        label='PDB Signal',
                        icon='󰱒' if pdb_signal else '󰄱',
                        action_id='settings:general:toggle_pdb',
                    ),
                    MenuItemData(
                        key='visual_debug',
                        label='Visual Debug',
                        icon='󰱒' if visual_debug else '󰄱',
                        action_id='settings:general:toggle_visual_debug',
                    ),
                    MenuItemData(
                        key='beta_versions',
                        label='Beta Versions',
                        icon='󰱒' if beta_versions else '󰄱',
                        action_id='settings:general:toggle_beta',
                    ),
                    MenuItemData(
                        key='grpc_remote_access',
                        label='gRPC Access',
                        icon='󰱒' if grpc_remote_access else '󰄱',
                        action_id='settings:general:toggle_grpc_remote_access',
                    ),
                ),
                placeholder='',
            ),
        )


# =============================================================================
# Third Party Settings
# =============================================================================


def _setup_third_party_settings() -> None:
    """Set up dynamic menu and action handlers for Third Party settings."""
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.services.audio import AudioInstallDriverAction
    from ubo_app.utils.eeprom import get_eeprom_data

    items: list[MenuItemData] = []

    eeprom_data = get_eeprom_data()
    if (
        eeprom_data['speakers'] is not None
        and eeprom_data['speakers']['model'] == 'wm8960'
    ):

        def _install_audio() -> None:
            store.dispatch(AudioInstallDriverAction())

        register_action('settings:third_party:install_audio', _install_audio)
        items.append(
            MenuItemData(
                key='install_audio',
                label='Re/Install Audio',
                icon='',
                action_id='settings:third_party:install_audio',
            ),
        )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=THIRD_PARTY_MENU_ID,
            title='Third Party Tools',
            items=tuple(items),
            placeholder='No third party tools',
        ),
    )


# =============================================================================
# Services Menu
# =============================================================================


def _setup_services_menu() -> None:
    """Set up dynamic menus and action handlers for Services settings."""
    from ubo_app.store.settings.service_menu_controller import (
        ServiceMenuController,
    )

    # Top-level services list autorun
    @store.autorun(
        lambda state: state.settings.services,
        options=AutorunOptions(default_value=None),
    )
    def _sync_services_list(
        services: dict[str, ServiceState] | None,
    ) -> None:
        if services is None:
            return

        items: list[MenuItemData] = []
        for service in sorted(services.values(), key=lambda x: x.label):
            # Set up per-service menus and action handlers (once per service)
            ServiceMenuController.setup_if_needed(service.id)

            # Determine icon based on status
            if service.is_active:
                icon = (
                    f'[color={WARNING_COLOR}]󰪥[/color]'
                    if service.errors
                    else f'[color={RUNNING_COLOR}]󰪥[/color]'
                )
            else:
                icon = f'[color={STOPPED_COLOR}]󰝦[/color]'

            items.append(
                MenuItemData(
                    key=service.id,
                    label=service.label,
                    icon=icon,
                    action_id=f'settings:service:{service.id}:navigate',
                ),
            )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=SERVICES_MENU_ID,
                title='Services',
                items=tuple(items),
                placeholder='No services',
            ),
        )


# =============================================================================
# Path Matcher Registration
# =============================================================================


def _register_system_path_matchers() -> None:
    """Register path matchers for System settings sub-menus."""
    from ubo_app.store.core.view_registry import register_path_menu_matcher

    def _system_path_matcher(path: tuple[str, ...]) -> str | None:
        if path == ('main', 'settings', 'System', 'general'):
            return GENERAL_MENU_ID
        if path == ('main', 'settings', 'System', 'services'):
            return SERVICES_MENU_ID
        if path == ('main', 'settings', 'System', 'third_party'):
            return THIRD_PARTY_MENU_ID

        # Per-service paths
        if (
            len(path) >= 5  # noqa: PLR2004
            and path[:3] == ('main', 'settings', 'System')
            and path[3] == 'services'
        ):
            service_id = path[4]
            if len(path) == 5:  # noqa: PLR2004
                return f'settings:service:{service_id}'
            if len(path) == 6:  # noqa: PLR2004
                sub_page = path[5]
                if sub_page == 'log_level':
                    return f'settings:service:{service_id}:log_level'
                if sub_page == 'errors':
                    return f'settings:service:{service_id}:errors'
        return None

    register_path_menu_matcher('system:settings', _system_path_matcher, priority=90)


# =============================================================================
# System Category Top-Level Items
# =============================================================================


def get_system_submenu_items() -> tuple[MenuItemData, ...]:
    """Return the static System sub-menu items (General, Services, Third Party).

    These items are prepended to the System category menu so that the
    autorun in menus.py doesn't overwrite them with only service entries.
    """
    return (
        MenuItemData(
            key='general',
            label='General',
            icon='\U000f0493',
            action_id=f'{MENU_NAVIGATE_PREFIX}settings:System:general',
        ),
        MenuItemData(
            key='services',
            label='Services',
            icon='\uf03a',
            action_id=f'{MENU_NAVIGATE_PREFIX}settings:System:services',
        ),
        MenuItemData(
            key='third_party',
            label='Third Party',
            icon='\uf08e',
            action_id=f'{MENU_NAVIGATE_PREFIX}settings:System:third_party',
        ),
    )


def _setup_system_category_items() -> None:
    """Register action handlers and dispatch System category items."""
    from ubo_app.store.core.action_registry import register_action

    def _navigate_to_general() -> None:
        store.dispatch(StackPushMenuAction(menu_key='general'))

    def _navigate_to_services() -> None:
        store.dispatch(StackPushMenuAction(menu_key='services'))

    def _navigate_to_third_party() -> None:
        store.dispatch(StackPushMenuAction(menu_key='third_party'))

    register_action(
        f'{MENU_NAVIGATE_PREFIX}settings:System:general',
        _navigate_to_general,
    )
    register_action(
        f'{MENU_NAVIGATE_PREFIX}settings:System:services',
        _navigate_to_services,
    )
    register_action(
        f'{MENU_NAVIGATE_PREFIX}settings:System:third_party',
        _navigate_to_third_party,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id='settings:System',
            title='\U000f0494System',
            items=get_system_submenu_items(),
            placeholder='',
        ),
    )


# =============================================================================
# Setup
# =============================================================================


def setup_dynamic_system_menus() -> None:
    """Set up all dynamic menus for System settings.

    Should be called after the store is initialized.
    """
    _register_system_path_matchers()
    _setup_system_category_items()
    _setup_general_settings()
    _setup_third_party_settings()
    _setup_services_menu()
