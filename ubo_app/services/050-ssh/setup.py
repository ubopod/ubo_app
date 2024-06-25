"""SSH service module."""

from __future__ import annotations

import asyncio
import socket
from typing import TYPE_CHECKING

from ubo_gui.constants import DANGER_COLOR, SUCCESS_COLOR
from ubo_gui.menu.types import (
    ActionItem,
    ApplicationItem,
    HeadedMenu,
    HeadlessMenu,
    Item,
    Menu,
    SubMenuItem,
)
from ubo_gui.prompt import PromptWidget

from ubo_app.store.core import (
    CloseApplicationEvent,
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.main import autorun, dispatch
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.ssh import SSHClearEnabledStateAction, SSHUpdateStateAction
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task
from ubo_app.utils.monitor_unit import is_unit_active, is_unit_enabled, monitor_unit
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.services.ssh import SSHState


class ClearTemporaryUsersPrompt(PromptWidget):
    """Prompt to clear all temporary users."""

    def first_option_callback(self: ClearTemporaryUsersPrompt) -> None:
        """Clear all temporary users."""
        dispatch(CloseApplicationEvent(application=self))

    def second_option_callback(self: ClearTemporaryUsersPrompt) -> None:
        """Close the prompt."""

        async def act() -> None:
            await send_command('service ssh clear_all_temporary_accounts')
            dispatch(
                CloseApplicationEvent(application=self),
                NotificationsAddAction(
                    notification=Notification(
                        title='All SSH Accounts Removed',
                        content='All SSH accounts have been removed.',
                        importance=Importance.MEDIUM,
                        icon='',
                        display_type=NotificationDisplayType.FLASH,
                    ),
                ),
            )

        create_task(act())

    def __init__(self: ClearTemporaryUsersPrompt, **kwargs: object) -> None:
        """Initialize the prompt."""
        super().__init__(**kwargs, items=None)
        self.prompt = 'Remove all temporary SSH accounts?'
        self.icon = '󱈋'
        self.first_option_label = ''
        self.first_option_background_color = 'black'
        self.first_option_is_short = False
        self.second_option_label = 'Delete'
        self.second_option_icon = '󱈊'
        self.second_option_is_short = False


def create_ssh_account() -> None:
    """Create a temporary SSH account."""

    async def act() -> None:
        if IS_RPI:
            result = await send_command(
                'service ssh create_temporary_ssh_account',
                has_output=True,
            )
        else:
            result = 'username:password'
        if not result:
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Failed to create temporary SSH account',
                        content='An error occurred while creating the temporary SSH '
                        'account.',
                        importance=Importance.MEDIUM,
                        icon='',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                    ),
                ),
            )

            return
        username, password = result.split(':')
        hostname = socket.gethostname()
        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Account Info',
                    content=f'[size=18dp][b]host:[/b] {hostname}\n'
                    f'[b]user:[/b] {username}\n[b]pass:[/b] {password}[/size]',
                    importance=Importance.MEDIUM,
                    icon='',
                    display_type=NotificationDisplayType.STICKY,
                    extra_information='Make sure to delete it after use.\n'
                    'Note that in order to make things work for you, we had to make '
                    'sure password authentication for {ssh|EH S EH S EY CH} server is '
                    'enabled, you may want to disable it later.',
                    color=SUCCESS_COLOR,
                ),
            ),
        )

    create_task(act())


def start_ssh_service() -> None:
    """Start the SSH service."""

    async def act() -> None:
        await send_command('service ssh start')

    create_task(act())


def stop_ssh_service() -> None:
    """Stop the SSH service."""

    async def act() -> None:
        await send_command('service ssh stop')

    create_task(act())


def enable_ssh_service() -> None:
    """Enable the SSH service."""

    async def act() -> None:
        dispatch(SSHClearEnabledStateAction())
        await send_command('service ssh enable')
        await asyncio.sleep(5)
        await check_is_ssh_enabled()

    create_task(act())


def disable_ssh_service() -> None:
    """Disable the SSH service."""

    async def act() -> None:
        dispatch(SSHClearEnabledStateAction())
        await send_command('service ssh disable')
        await asyncio.sleep(5)
        await check_is_ssh_enabled()

    create_task(act())


@autorun(lambda state: state.ssh)
def ssh_items(state: SSHState) -> Sequence[Item]:
    """Get the SSH menu items."""
    return [
        SubMenuItem(
            label='Create account',
            icon='',
            sub_menu=HeadedMenu(
                title='SSH Setup',
                heading='Create an SSH account',
                sub_heading='This will create a temporary SSH account,\n'
                'you should delete it after use.',
                items=[
                    ActionItem(
                        label='Create',
                        icon='󰗹',
                        action=create_ssh_account,
                    ),
                ],
            ),
        ),
        ApplicationItem(
            label='Remove all users',
            icon='󱈊',
            application=ClearTemporaryUsersPrompt,
        ),
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


@autorun(lambda state: state.ssh)
def ssh_icon(state: SSHState) -> str:
    """Get the SSH icon."""
    return '[color=#008000]󰪥[/color]' if state.is_active else '[color=#ffff00]󰝦[/color]'


@autorun(lambda state: state.ssh)
def ssh_title(_: SSHState) -> str:
    """Get the SSH title."""
    return ssh_icon() + ' SSH'


async def check_is_ssh_active() -> None:
    """Check if the SSH service is active."""
    if await is_unit_active('ssh'):
        dispatch(SSHUpdateStateAction(is_enabled=True))
    else:
        dispatch(SSHUpdateStateAction(is_enabled=False))


async def check_is_ssh_enabled() -> None:
    """Check if the SSH service is enabled."""
    if await is_unit_enabled('ssh'):
        dispatch(SSHUpdateStateAction(is_enabled=True))
    else:
        dispatch(SSHUpdateStateAction(is_enabled=False))


def open_ssh_menu() -> Menu:
    """Open the SSH menu."""
    create_task(
        asyncio.gather(
            check_is_ssh_active(),
            check_is_ssh_enabled(),
        ),
    )

    return HeadlessMenu(
        title=ssh_title,
        items=ssh_items,
    )


def init_service() -> None:
    """Initialize the SSH service."""
    dispatch(
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

    create_task(
        asyncio.gather(
            check_is_ssh_active(),
            check_is_ssh_enabled(),
            monitor_unit(
                'ssh.service',
                lambda status: dispatch(
                    SSHUpdateStateAction(
                        is_active=status in ('active', 'activating', 'reloading'),
                    ),
                ),
            ),
        ),
    )
