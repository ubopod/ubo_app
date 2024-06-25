"""LightDM service module."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ubo_gui.menu.types import ActionItem, HeadlessMenu, Item, Menu

from ubo_app.store.core import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import autorun, dispatch
from ubo_app.store.services.lightdm import (
    LightDMClearEnabledStateAction,
    LightDMUpdateStateAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.monitor_unit import is_unit_active, is_unit_enabled, monitor_unit
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.services.lightdm import LightDMState


def start_lightdm_service() -> None:
    """Start the LightDM service."""

    async def act() -> None:
        await send_command('service lightdm start')

    create_task(act())


def stop_lightdm_service() -> None:
    """Stop the LightDM service."""

    async def act() -> None:
        await send_command('service lightdm stop')

    create_task(act())


def enable_lightdm_service() -> None:
    """Enable the LightDM service."""

    async def act() -> None:
        dispatch(LightDMClearEnabledStateAction())
        await send_command('service lightdm enable')
        await asyncio.sleep(5)
        await check_is_lightdm_enabled()

    create_task(act())


def disable_lightdm_service() -> None:
    """Disable the LightDM service."""

    async def act() -> None:
        dispatch(LightDMClearEnabledStateAction())
        await send_command('service lightdm disable')
        await asyncio.sleep(5)
        await check_is_lightdm_enabled()

    create_task(act())


@autorun(lambda state: state.lightdm)
def lightdm_items(state: LightDMState) -> Sequence[Item]:
    """Get the LightDM menu items."""
    return [
        ActionItem(
            label='Stop' if state.is_active else 'Start',
            icon='󰓛' if state.is_active else '󰐊',
            action=stop_lightdm_service if state.is_active else start_lightdm_service,
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
    ]


@autorun(lambda state: state.lightdm)
def lightdm_icon(state: LightDMState) -> str:
    """Get the LightDM icon."""
    return '[color=#008000]󰪥[/color]' if state.is_active else '[color=#ffff00]󰝦[/color]'


@autorun(lambda state: state.lightdm)
def lightdm_title(_: LightDMState) -> str:
    """Get the LightDM title."""
    return lightdm_icon() + ' LightDM'


async def check_is_lightdm_active() -> None:
    """Check if the LightDM service is active."""
    if await is_unit_active('lightdm'):
        dispatch(LightDMUpdateStateAction(is_enabled=True))
    else:
        dispatch(LightDMUpdateStateAction(is_enabled=False))


async def check_is_lightdm_enabled() -> None:
    """Check if the LightDM service is enabled."""
    if await is_unit_enabled('lightdm'):
        dispatch(LightDMUpdateStateAction(is_enabled=True))
    else:
        dispatch(LightDMUpdateStateAction(is_enabled=False))


def open_lightdm_menu() -> Menu:
    """Open the LightDM menu."""
    create_task(
        asyncio.gather(
            check_is_lightdm_active(),
            check_is_lightdm_enabled(),
        ),
    )

    return HeadlessMenu(
        title=lightdm_title,
        items=lightdm_items,
    )


def init_service() -> None:
    """Initialize the LightDM service."""
    dispatch(
        RegisterSettingAppAction(
            priority=0,
            category=SettingsCategory.UTILITIES,
            menu_item=ActionItem(
                label='LightDM',
                icon=lightdm_icon,
                action=open_lightdm_menu,
            ),
        ),
    )

    create_task(
        asyncio.gather(
            check_is_lightdm_active(),
            check_is_lightdm_enabled(),
            monitor_unit(
                'lightdm.service',
                lambda status: dispatch(
                    LightDMUpdateStateAction(
                        is_active=status in ('active', 'activating', 'reloading'),
                    ),
                ),
            ),
        ),
    )
