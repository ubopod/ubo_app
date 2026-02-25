"""LightDM service module."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from redux import AutorunOptions
from ubo_gui.constants import WARNING_COLOR
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, Item, Menu

from ubo_app.colors import DANGER_COLOR, RUNNING_COLOR, STOPPED_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.lightdm import (
    LightDMClearEnabledStateAction,
    LightDMUpdateStateAction,
)
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.apt import is_package_installed
from ubo_app.utils.async_ import create_task
from ubo_app.utils.monitor_unit import is_unit_enabled, monitor_unit
from ubo_app.utils.server import send_command

# Dynamic menu ID for dumb UI architecture
LIGHTDM_MENU_ID = 'lightdm:main'

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.services.lightdm import LightDMState


def install_lightdm() -> None:
    """Install LightDM."""

    async def act() -> None:
        store.dispatch(LightDMUpdateStateAction(is_installing=True))
        result = await send_command(
            'package',
            'install',
            'lightdm',
            has_output=True,
        )
        store.dispatch(LightDMUpdateStateAction(is_installing=False))
        if result != 'installed':
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Desktop',
                        content='Failed to install',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
        await check_lightdm()

    create_task(act())


def start_lightdm_service() -> None:
    """Start the LightDM service."""
    create_task(send_command('service', 'lightdm', 'start'))


def stop_lightdm_service() -> None:
    """Stop the LightDM service."""
    create_task(send_command('service', 'lightdm', 'stop'))


def enable_lightdm_service() -> None:
    """Enable the LightDM service."""

    async def act() -> None:
        store.dispatch(LightDMClearEnabledStateAction())
        await send_command('service', 'lightdm', 'enable')
        await asyncio.sleep(5)
        await check_lightdm()

    create_task(act())


@store.autorun(
    lambda state: state.lightdm,
    options=AutorunOptions(default_value=f'[color={WARNING_COLOR}][/color]'),
)
def lightdm_icon(state: LightDMState) -> str:
    """Get the LightDM icon."""
    return (
        f'[color={RUNNING_COLOR}]󰪥[/color]'
        if state.is_active
        else f'[color={STOPPED_COLOR}]󰝦[/color]'
    )


@store.autorun(lambda state: state.lightdm)
def lightdm_title(_: LightDMState) -> str:
    """Get the LightDM title."""
    return lightdm_icon() + ' Desktop'


def disable_lightdm_service() -> None:
    """Disable the LightDM service."""

    async def act() -> None:
        store.dispatch(LightDMClearEnabledStateAction())
        await send_command('service', 'lightdm', 'disable')
        await asyncio.sleep(5)
        await check_lightdm()

    create_task(act())


def _register_lightdm_action_handlers() -> None:
    """Register action handlers for LightDM menu items."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
    )

    # Only register once
    if 'lightdm:install' in get_registered_actions():
        return

    register_action('lightdm:install', install_lightdm)
    register_action('lightdm:start', start_lightdm_service)
    register_action('lightdm:stop', stop_lightdm_service)
    register_action('lightdm:enable', enable_lightdm_service)
    register_action('lightdm:disable', disable_lightdm_service)


@store.autorun(lambda state: state.lightdm)
def update_lightdm_dynamic_menu(state: LightDMState) -> None:
    """Update the dynamic menu for LightDM (dumb UI architecture)."""
    # Register action handlers on first call
    _register_lightdm_action_handlers()

    items: list[MenuItemData] = []
    placeholder = ''

    if state.is_installing:
        placeholder = 'Installing Desktop...'
    elif not state.is_installed:
        items.append(
            MenuItemData(
                key='lightdm:install',
                label='Install Desktop',
                icon='󰶮',
                action_id='lightdm:install',
            ),
        )
    else:
        # Start/Stop item
        items.append(
            MenuItemData(
                key='lightdm:toggle',
                label='Stop' if state.is_active else 'Start',
                icon='󰓛' if state.is_active else '󰐊',
                action_id='lightdm:stop' if state.is_active else 'lightdm:start',
            ),
        )

        # Enable/Disable item
        if state.is_enabled is None:
            items.append(
                MenuItemData(
                    key='lightdm:enabled-status',
                    label='...',
                    icon='',
                ),
            )
        elif state.is_enabled:
            items.append(
                MenuItemData(
                    key='lightdm:disable',
                    label='Disable',
                    icon='󰯄',
                    action_id='lightdm:disable',
                ),
            )
        else:
            items.append(
                MenuItemData(
                    key='lightdm:enable',
                    label='Enable',
                    icon='󰯅',
                    action_id='lightdm:enable',
                ),
            )

    logger.debug(
        '[LightDM Service] Updating dynamic menu: is_installed=%s, is_active=%s',
        state.is_installed,
        state.is_active,
    )

    # Compute dynamic heading/sub_heading from state
    heading: str | None = None
    sub_heading: str | None = None
    if state.is_installing:
        heading = 'Installing Desktop'
        sub_heading = 'This may take a few minutes'
    elif not state.is_installed:
        heading = 'Desktop is not Installed'
        sub_heading = 'Install it to enable desktop access on your Ubo pod'

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=LIGHTDM_MENU_ID,
            title='Desktop',
            heading=heading,
            sub_heading=sub_heading,
            items=tuple(items),
            placeholder=placeholder,
        ),
    )


@store.autorun(lambda state: state.lightdm)
def lightdm_menu(state: LightDMState) -> Menu:
    """Get the LightDM menu items."""
    if state.is_installing:
        return HeadedMenu(
            title=lightdm_title,
            heading='Installing Desktop',
            sub_heading='This may take a few minutes',
            items=[],
        )
    if not state.is_installed:
        return HeadedMenu(
            title=lightdm_title,
            heading='Desktop is not Installed',
            sub_heading='Install it to enable desktop access on your Ubo pod',
            items=[
                ActionItem(
                    label='Install Desktop',
                    icon='󰶮',
                    action=install_lightdm,
                ),
            ],
        )
    return HeadlessMenu(
        title=lightdm_title,
        items=[
            ActionItem(
                label='Stop' if state.is_active else 'Start',
                icon='󰓛' if state.is_active else '󰐊',
                action=stop_lightdm_service
                if state.is_active
                else start_lightdm_service,
            ),
            Item(
                label='...',
                icon='',
            )
            if state.is_enabled is None
            else ActionItem(
                label='Disable',
                icon=f'[color={RUNNING_COLOR}]󰯄[/color]',
                action=disable_lightdm_service,
            )
            if state.is_enabled
            else ActionItem(
                label='Enable',
                icon=f'[color={STOPPED_COLOR}]󰯅[/color]',
                action=enable_lightdm_service,
            ),
        ],
    )


async def check_lightdm() -> None:
    """Check if the LightDM service is enabled."""
    is_enabled, is_installed = await asyncio.gather(
        is_unit_enabled('lightdm'),
        is_package_installed('raspberrypi-ui-mods'),
    )

    store.dispatch(
        LightDMUpdateStateAction(
            is_enabled=is_installed and is_enabled,
            is_installed=is_installed,
        ),
    )


def open_lightdm_menu() -> Callable[[], Menu]:
    """Open the LightDM menu."""
    create_task(check_lightdm())

    return lightdm_menu


def init_service() -> None:
    """Initialize the LightDM service."""
    from ubo_app.store.core.action_registry import register_action

    register_action('lightdm:open_menu', open_lightdm_menu)
    store.dispatch(
        RegisterSettingAppAction(
            priority=0,
            category=SettingsCategory.SYSTEM,
            label='Desktop',
            icon='󰍹',
            action_id='lightdm:open_menu',
        ),
    )

    from ubo_app.store.core.view_registry import register_path_menu_matcher

    register_path_menu_matcher(
        'lightdm:settings',
        lambda path: LIGHTDM_MENU_ID
        if len(path) >= 4  # noqa: PLR2004
        and path[3] == 'lightdm:'
        else None,
    )

    create_task(check_lightdm())
    create_task(
        monitor_unit(
            'lightdm.service',
            lambda status: store.dispatch(
                LightDMUpdateStateAction(
                    is_active=status in ('active', 'activating', 'reloading'),
                ),
            ),
        ),
    )
