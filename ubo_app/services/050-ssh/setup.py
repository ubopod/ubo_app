"""SSH service module."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from redux import AutorunOptions
from ubo_gui.constants import WARNING_COLOR
from ubo_gui.menu.types import ActionItem, HeadlessMenu, Item, Menu

from ubo_app.colors import RUNNING_COLOR, STOPPED_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.ssh import SSHClearEnabledStateAction, SSHUpdateStateAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.monitor_unit import is_unit_enabled, monitor_unit
from ubo_app.utils.server import send_command

# Dynamic menu IDs for dumb UI architecture
SSH_MENU_ID = 'ssh:main'

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


def _register_ssh_action_handlers() -> None:
    """Register action handlers for SSH menu items."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
    )

    # Only register once
    if 'ssh:start' in get_registered_actions():
        return

    register_action('ssh:start', start_ssh_service)
    register_action('ssh:stop', stop_ssh_service)
    register_action('ssh:enable', enable_ssh_service)
    register_action('ssh:disable', disable_ssh_service)


@store.autorun(lambda state: state.ssh)
def update_ssh_dynamic_menu(state: SSHState) -> None:
    """Update the dynamic menu for SSH (dumb UI architecture)."""
    # Register action handlers on first call
    _register_ssh_action_handlers()

    # Build items based on current state
    items: list[MenuItemData] = [
        MenuItemData(
            key='ssh:toggle',
            label='Stop' if state.is_active else 'Start',
            icon='󰓛' if state.is_active else '󰐊',
            action_id='ssh:stop' if state.is_active else 'ssh:start',
        ),
    ]

    # Add enable/disable item based on enabled state
    if state.is_enabled is None:
        items.append(
            MenuItemData(
                key='ssh:enabled-status',
                label='...',
                icon='',
            ),
        )
    elif state.is_enabled:
        items.append(
            MenuItemData(
                key='ssh:disable',
                label='Disable',
                icon='󰯄',  # Note: color markup not supported in MenuItemData.icon yet
                action_id='ssh:disable',
            ),
        )
    else:
        items.append(
            MenuItemData(
                key='ssh:enable',
                label='Enable',
                icon='󰯅',
                action_id='ssh:enable',
            ),
        )

    logger.debug(
        '[SSH Service] Updating dynamic menu: is_active=%s, is_enabled=%s',
        state.is_active,
        state.is_enabled,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=SSH_MENU_ID,
            title='SSH',
            items=tuple(items),
            placeholder='',
        ),
    )


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
            icon=f'[color={RUNNING_COLOR}]󰯄[/color]',
            action=disable_ssh_service,
        )
        if state.is_enabled
        else ActionItem(
            label='Enable',
            icon=f'[color={STOPPED_COLOR}]󰯅[/color]',
            action=enable_ssh_service,
        ),
    ]


@store.autorun(
    lambda state: state.ssh,
    options=AutorunOptions(default_value=f'[color={WARNING_COLOR}][/color]'),
)
def ssh_icon(state: SSHState) -> str:
    """Get the SSH icon."""
    return (
        f'[color={RUNNING_COLOR}]󰪥[/color]'
        if state.is_active
        else f'[color={STOPPED_COLOR}]󰝦[/color]'
    )


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
    from ubo_app.store.core.action_registry import register_action

    register_action('ssh:open_menu', open_ssh_menu)
    store.dispatch(
        RegisterSettingAppAction(
            priority=1,
            category=SettingsCategory.REMOTE,
            label='SSH',
            icon='󰣀',
            action_id='ssh:open_menu',
        ),
    )

    from ubo_app.store.core.view_registry import register_path_menu_matcher

    register_path_menu_matcher(
        'ssh:settings',
        lambda path: SSH_MENU_ID
        if len(path) >= 4  # noqa: PLR2004
        and path[3] == 'ssh:'
        else None,
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
