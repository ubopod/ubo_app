"""LightDM service module."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ubo_gui.constants import DANGER_COLOR
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, Item, Menu

from ubo_app.store.core import RegisterSettingAppAction, SettingsCategory
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


@store.autorun(lambda state: state.lightdm)
def lightdm_icon(state: LightDMState) -> str:
    """Get the LightDM icon."""
    return '[color=#008000]󰪥[/color]' if state.is_active else '[color=#ffff00]󰝦[/color]'


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
                icon='[color=#008000]󰯄[/color]',
                action=disable_lightdm_service,
            )
            if state.is_enabled
            else ActionItem(
                label='Enable',
                icon='[color=#ffff00]󰯅[/color]',
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
    store.dispatch(
        RegisterSettingAppAction(
            priority=0,
            category=SettingsCategory.OS,
            menu_item=ActionItem(
                label='Desktop',
                icon=lightdm_icon,
                action=open_lightdm_menu,
            ),
        ),
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
