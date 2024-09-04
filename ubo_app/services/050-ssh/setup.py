"""SSH service module."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ubo_gui.menu.types import ActionItem, HeadlessMenu, Item, Menu

from ubo_app.store.core import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.ssh import SSHClearEnabledStateAction, SSHUpdateStateAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.monitor_unit import is_unit_enabled, monitor_unit
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.services.ssh import SSHState


def start_ssh_service() -> None:
    """Start the SSH service."""
    create_task(send_command('service', 'ssh', 'start'))


def stop_ssh_service() -> None:
    """Stop the SSH service."""
    create_task(send_command('service', 'ssh', 'stop'))


def enable_ssh_service() -> None:
    """Enable the SSH service."""

    async def act() -> None:
        store.dispatch(SSHClearEnabledStateAction())
        await send_command('service', 'ssh', 'enable')
        await asyncio.sleep(5)
        await check_is_ssh_enabled()

    create_task(act())


def disable_ssh_service() -> None:
    """Disable the SSH service."""

    async def act() -> None:
        store.dispatch(SSHClearEnabledStateAction())
        await send_command('service', 'ssh', 'disable')
        await asyncio.sleep(5)
        await check_is_ssh_enabled()

    create_task(act())


@store.autorun(lambda state: state.ssh)
def ssh_items(state: SSHState) -> Sequence[Item]:
    """Get the SSH menu items."""
    return [
        ActionItem(
            label='Stop' if state.is_active else 'Start',
            icon='󰓛' if state.is_active else '󰐊',
            action=stop_ssh_service if state.is_active else start_ssh_service,
        ),
        Item(
            label='...',
            icon='',
        )
        if state.is_enabled is None
        else ActionItem(
            label='Disable',
            icon='[color=#008000]󰯄[/color]',
            action=disable_ssh_service,
        )
        if state.is_enabled
        else ActionItem(
            label='Enable',
            icon='[color=#ffff00]󰯅[/color]',
            action=enable_ssh_service,
        ),
    ]


@store.autorun(lambda state: state.ssh)
def ssh_icon(state: SSHState) -> str:
    """Get the SSH icon."""
    return '[color=#008000]󰪥[/color]' if state.is_active else '[color=#ffff00]󰝦[/color]'


@store.autorun(lambda state: state.ssh)
def ssh_title(_: SSHState) -> str:
    """Get the SSH title."""
    return ssh_icon() + ' SSH'


async def check_is_ssh_enabled() -> None:
    """Check if the SSH service is enabled."""
    if await is_unit_enabled('ssh'):
        store.dispatch(SSHUpdateStateAction(is_enabled=True))
    else:
        store.dispatch(SSHUpdateStateAction(is_enabled=False))


def open_ssh_menu() -> Menu:
    """Open the SSH menu."""
    create_task(check_is_ssh_enabled())

    return HeadlessMenu(title=ssh_title, items=ssh_items)


def init_service() -> None:
    """Initialize the SSH service."""
    store.dispatch(
        RegisterSettingAppAction(
            priority=1,
            category=SettingsCategory.REMOTE,
            menu_item=ActionItem(
                label='SSH',
                icon=ssh_icon,
                action=open_ssh_menu,
            ),
        ),
    )

    create_task(check_is_ssh_enabled())
    create_task(
        monitor_unit(
            'ssh.service',
            lambda status: store.dispatch(
                SSHUpdateStateAction(
                    is_active=status in ('active', 'activating', 'reloading'),
                ),
            ),
        ),
    )
