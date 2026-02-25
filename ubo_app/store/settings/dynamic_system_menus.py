"""Dynamic menus for System settings (General, Services, Third Party).

Replaces the static SYSTEM_MENU from settings/menu.py with dynamic menus
that update via autoruns and the action registry.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from redux import AutorunOptions

from ubo_app import logger
from ubo_app.colors import DANGER_COLOR, RUNNING_COLOR, STOPPED_COLOR, WARNING_COLOR
from ubo_app.store.core.types import (
    MenuItemData,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store

if TYPE_CHECKING:
    from ubo_app.store.settings.types import ErrorReport, ServiceState

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
        SettingsTogglePdbSignalAction,
        SettingsToggleVisualDebugAction,
    )

    def _toggle_pdb() -> None:
        store.dispatch(SettingsTogglePdbSignalAction())

    def _toggle_visual_debug() -> None:
        store.dispatch(SettingsToggleVisualDebugAction())

    def _toggle_beta() -> None:
        store.dispatch(SettingsToggleBetaVersionsAction())

    register_action('settings:general:toggle_pdb', _toggle_pdb)
    register_action('settings:general:toggle_visual_debug', _toggle_visual_debug)
    register_action('settings:general:toggle_beta', _toggle_beta)

    @store.autorun(
        lambda state: (
            state.settings.pdb_signal,
            state.settings.visual_debug,
            state.settings.beta_versions,
        ),
        options=AutorunOptions(default_value=None),
    )
    def _sync_general_menu(
        data: tuple[bool, bool, bool] | None,
    ) -> None:
        if data is None:
            return
        pdb_signal, visual_debug, beta_versions = data

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
    from ubo_app.store.core.action_registry import register_action

    # Track which per-service autoruns are set up
    _setup_service_ids: set[str] = set()

    def _setup_per_service_menus(service_id: str) -> None:
        """Set up dynamic menus for a single service."""
        if service_id in _setup_service_ids:
            return
        _setup_service_ids.add(service_id)

        service_menu_id = f'settings:service:{service_id}'
        log_level_menu_id = f'settings:service:{service_id}:log_level'
        errors_menu_id = f'settings:service:{service_id}:errors'

        # Register navigation actions for this service
        def _navigate_to_service() -> None:
            store.dispatch(StackPushMenuAction(menu_key=service_id))

        def _navigate_to_log_level() -> None:
            store.dispatch(StackPushMenuAction(menu_key=f'{service_id}:log_level'))

        def _navigate_to_errors() -> None:
            store.dispatch(StackPushMenuAction(menu_key=f'{service_id}:errors'))

        register_action(f'settings:service:{service_id}:navigate', _navigate_to_service)
        register_action(
            f'settings:service:{service_id}:navigate_log_level',
            _navigate_to_log_level,
        )
        register_action(
            f'settings:service:{service_id}:navigate_errors',
            _navigate_to_errors,
        )

        # Register action handlers for service operations
        from ubo_app.store.settings.types import (
            SettingsClearServiceErrorsAction,
            SettingsServiceSetIsEnabledAction,
            SettingsServiceSetLogLevelAction,
            SettingsServiceSetShouldRestartAction,
            SettingsStartServiceAction,
            SettingsStopServiceAction,
        )

        def _stop_service() -> None:
            store.dispatch(SettingsStopServiceAction(service_id=service_id))

        def _start_service() -> None:
            store.dispatch(SettingsStartServiceAction(service_id=service_id))

        def _toggle_enabled(*, enable: bool) -> None:
            store.dispatch(
                SettingsServiceSetIsEnabledAction(
                    service_id=service_id,
                    is_enabled=enable,
                ),
            )

        def _toggle_restart(*, should_restart: bool) -> None:
            store.dispatch(
                SettingsServiceSetShouldRestartAction(
                    service_id=service_id,
                    should_auto_restart=should_restart,
                ),
            )

        def _clear_errors() -> None:
            store.dispatch(
                SettingsClearServiceErrorsAction(service_id=service_id),
            )

        register_action(f'settings:service:{service_id}:stop', _stop_service)
        register_action(f'settings:service:{service_id}:start', _start_service)
        register_action(
            f'settings:service:{service_id}:enable',
            lambda: _toggle_enabled(enable=True),
        )
        register_action(
            f'settings:service:{service_id}:disable',
            lambda: _toggle_enabled(enable=False),
        )
        register_action(
            f'settings:service:{service_id}:enable_restart',
            lambda: _toggle_restart(should_restart=True),
        )
        register_action(
            f'settings:service:{service_id}:disable_restart',
            lambda: _toggle_restart(should_restart=False),
        )
        register_action(
            f'settings:service:{service_id}:clear_errors',
            _clear_errors,
        )

        # Register log level action handlers
        for level in logger.COLORS_HEX:

            def _set_log_level(*, _level: int = level) -> None:
                store.dispatch(
                    SettingsServiceSetLogLevelAction(
                        service_id=service_id,
                        log_level=_level,
                    ),
                )

            register_action(
                f'settings:service:{service_id}:log_level:{level}',
                _set_log_level,
            )

        # Register error item action handlers (open raw-text-viewer)
        def _make_error_action(error_msg: str) -> None:
            from ubo_app.store.core.types import StackPushApplicationAction

            store.dispatch(
                StackPushApplicationAction(
                    application_id='ubo:raw-text-viewer',
                    initialization_kwargs={'text': error_msg},
                ),
            )

        # Per-service detail page autorun
        @store.autorun(
            lambda state, _sid=service_id: state.settings.services.get(_sid),
            options=AutorunOptions(default_value=None),
        )
        def _sync_service_detail(
            service_state: ServiceState | None,
            *,
            _sid: str = service_id,
            _menu_id: str = service_menu_id,
        ) -> None:
            if service_state is None:
                return

            items: list[MenuItemData] = []

            # Start/Stop
            if service_state.is_active:
                items.append(
                    MenuItemData(
                        key='stop',
                        label='Stop',
                        icon='',
                        background_color=DANGER_COLOR,
                        action_id=f'settings:service:{_sid}:stop',
                    ),
                )
            else:
                items.append(
                    MenuItemData(
                        key='start',
                        label='Start',
                        icon=f'[color={RUNNING_COLOR}][/color]',
                        action_id=f'settings:service:{_sid}:start',
                    ),
                )

            # Enable/Disable
            if service_state.is_enabled:
                items.append(
                    MenuItemData(
                        key='enabled',
                        label='Auto Load',
                        icon='',
                        action_id=f'settings:service:{_sid}:disable',
                    ),
                )
                # Log level navigation
                items.append(
                    MenuItemData(
                        key='log_level',
                        label=(
                            f'Level: '
                            f'{logging.getLevelName(service_state.log_level)}'
                        ),
                        icon='',
                        background_color=logger.COLORS_HEX[service_state.log_level],
                        action_id=(
                            f'settings:service:{_sid}:navigate_log_level'
                        ),
                    ),
                )
            else:
                items.append(
                    MenuItemData(
                        key='enabled',
                        label='Auto Load',
                        icon='',
                        background_color='#000000',
                        action_id=f'settings:service:{_sid}:enable',
                    ),
                )

            # Auto Restart
            if service_state.should_auto_restart:
                items.append(
                    MenuItemData(
                        key='auto_restart',
                        label='Auto Restart',
                        icon='󰜉',
                        action_id=f'settings:service:{_sid}:disable_restart',
                    ),
                )
            else:
                items.append(
                    MenuItemData(
                        key='auto_restart',
                        label='Auto Restart',
                        icon='󰶕',
                        background_color='#000000',
                        action_id=f'settings:service:{_sid}:enable_restart',
                    ),
                )

            # Errors
            if service_state.errors:
                items.append(
                    MenuItemData(
                        key='errors',
                        label='Errors',
                        icon=f'[color={DANGER_COLOR}][/color]',
                        action_id=f'settings:service:{_sid}:navigate_errors',
                    ),
                )
                items.append(
                    MenuItemData(
                        key='clear_errors',
                        label='Clear errors',
                        icon='',
                        action_id=f'settings:service:{_sid}:clear_errors',
                    ),
                )

            # Heading
            errors = service_state.errors
            heading = (
                (
                    f'[color={WARNING_COLOR}]󰪥[/color] {service_state.label}'
                    if errors
                    else f'[color={RUNNING_COLOR}]󰪥[/color] {service_state.label}'
                )
                if service_state.is_active
                else f'[color={STOPPED_COLOR}]󰝦[/color] {service_state.label}'
            )

            # Sub heading
            if not errors:
                sub_heading = 'No errors raised in this service'
            elif len(errors) == 1:
                sub_heading = '1 error raised in this service'
            else:
                sub_heading = f'{len(errors)} errors raised in this service'

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=_menu_id,
                    title=service_state.label,
                    heading=heading,
                    sub_heading=sub_heading,
                    items=tuple(items),
                    placeholder='',
                ),
            )

        # Log level page autorun
        @store.autorun(
            lambda state, _sid=service_id: (
                state.settings.services[_sid].log_level
                if state.settings.services and _sid in state.settings.services
                else None
            ),
            options=AutorunOptions(default_value=None),
        )
        def _sync_log_level_menu(
            log_level: int | None,
            *,
            _sid: str = service_id,
            _menu_id: str = log_level_menu_id,
        ) -> None:
            if log_level is None:
                return

            items: list[MenuItemData] = []
            for level in logger.COLORS_HEX:
                is_selected = level == log_level
                bg_color = (
                    logger.COLORS_HEX[level] if is_selected else '#000000'
                )
                color = (
                    '#ffffff' if is_selected else logger.COLORS_HEX[level]
                )
                icon = '󰱒' if is_selected else '󰄱'

                items.append(
                    MenuItemData(
                        key=logging.getLevelName(level),
                        label=logging.getLevelName(level),
                        icon=icon,
                        color=color,
                        background_color=bg_color,
                        action_id=f'settings:service:{_sid}:log_level:{level}',
                    ),
                )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=_menu_id,
                    title=f'Log Level: {logging.getLevelName(log_level)}',
                    items=tuple(items),
                    placeholder='',
                ),
            )

        # Errors page autorun
        @store.autorun(
            lambda state, _sid=service_id: (
                state.settings.services[_sid].errors
                if state.settings.services and _sid in state.settings.services
                else None
            ),
            options=AutorunOptions(default_value=None),
        )
        def _sync_errors_menu(
            errors: list[ErrorReport] | None,
            *,
            _sid: str = service_id,
            _menu_id: str = errors_menu_id,
        ) -> None:
            if errors is None:
                return

            items: list[MenuItemData] = []
            for index, error in enumerate(errors):
                # Register action handler for this specific error
                error_action_id = (
                    f'settings:service:{_sid}:error:{index}'
                )
                register_action(
                    error_action_id,
                    lambda _msg=error.message: _make_error_action(_msg),
                )
                items.append(
                    MenuItemData(
                        key=str(index),
                        label=datetime.datetime.fromtimestamp(
                            error.timestamp,
                        )
                        .astimezone()
                        .strftime('%Y-%m-%d %H:%M:%S'),
                        icon=f'[color={DANGER_COLOR}][/color]',
                        action_id=error_action_id,
                    ),
                )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=_menu_id,
                    title='Errors',
                    heading='Errors',
                    sub_heading='Errors raised in this service',
                    items=tuple(items),
                    placeholder='No errors',
                ),
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
            # Set up per-service menus and action handlers
            _setup_per_service_menus(service.id)

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


def _setup_system_category_items() -> None:
    """Register action handlers and dispatch System category items."""
    from ubo_app.store.core.action_registry import register_action

    def _navigate_to_general() -> None:
        store.dispatch(StackPushMenuAction(menu_key='general'))

    def _navigate_to_services() -> None:
        store.dispatch(StackPushMenuAction(menu_key='services'))

    def _navigate_to_third_party() -> None:
        store.dispatch(StackPushMenuAction(menu_key='third_party'))

    register_action('menu:navigate:settings:System:general', _navigate_to_general)
    register_action('menu:navigate:settings:System:services', _navigate_to_services)
    register_action(
        'menu:navigate:settings:System:third_party',
        _navigate_to_third_party,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id='settings:System',
            title='󰒔System',
            items=(
                MenuItemData(
                    key='general',
                    label='General',
                    icon='󰒓',
                    action_id='menu:navigate:settings:System:general',
                ),
                MenuItemData(
                    key='services',
                    label='Services',
                    icon='',
                    action_id='menu:navigate:settings:System:services',
                ),
                MenuItemData(
                    key='third_party',
                    label='Third Party',
                    icon='',
                    action_id='menu:navigate:settings:System:third_party',
                ),
            ),
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
