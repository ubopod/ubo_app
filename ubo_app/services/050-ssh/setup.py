"""SSH service module."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Sequence

from ubo_gui.menu.types import (
    ActionItem,
    ApplicationItem,
    HeadedMenu,
    HeadlessMenu,
    Item,
    SubMenuItem,
)
from ubo_gui.prompt import PromptWidget

from ubo_app.store import autorun, dispatch
from ubo_app.store.main import RegisterSettingAppAction
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.ssh import SSHUpdateStateAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from ubo_app.store.services.ssh import SSHState


class ClearTemporaryUsersPrompt(PromptWidget):
    """Prompt to clear all temporary users."""

    def first_option_callback(self: ClearTemporaryUsersPrompt) -> None:
        """Clear all temporary users."""
        self.dispatch('on_close')

    def second_option_callback(self: ClearTemporaryUsersPrompt) -> None:
        """Close the prompt."""
        send_command('ssh clear_all_temporary_accounts')
        self.dispatch('on_close')
        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='All SSH Accounts Removed',
                    content='All SSH accounts have been removed.',
                    importance=Importance.MEDIUM,
                    icon='󰣀',
                    display_type=NotificationDisplayType.FLASH,
                ),
            ),
        )

    def __init__(self: ClearTemporaryUsersPrompt, **kwargs: object) -> None:
        """Initialize the prompt."""
        super().__init__(**kwargs, items=None)
        self.prompt = 'Clear temporary ssh users?'
        self.icon = '󱈋'
        self.first_option_label = ''
        self.first_option_background_color = 'black'
        self.first_option_is_short = False
        self.second_option_label = 'Delete'
        self.second_option_icon = '󱈊'
        self.second_option_is_short = False


def create_ssh_account() -> None:
    """Create a temporary SSH account."""
    result = send_command('ssh create_temporary_ssh_account', has_output=True)
    username, password = result.split(':')
    dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='Temporary SSH Account Created',
                content=f"""Username: {username}
Password: {password}
Make sure to delete it after use. Note that in order to make things work for you, we \
had to make sure password authentication for ssh server is enabled, you may want to \
disable it later.""",
                importance=Importance.MEDIUM,
                icon='󰣀',
                display_type=NotificationDisplayType.STICKY,
            ),
        ),
    )


def start_ssh_service() -> None:
    """Start the SSH service."""
    send_command('ssh start')


def stop_ssh_service() -> None:
    """Stop the SSH service."""
    send_command('ssh stop')


def enable_ssh_service() -> None:
    """Enable the SSH service."""
    send_command('ssh enable')


def disable_ssh_service() -> None:
    """Disable the SSH service."""
    send_command('ssh disable')


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
                sub_heading='This will create a temporary SSH account,'
                ' you should delete it after use.',
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
        ActionItem(
            label='Disable' if state.is_enabled else 'Enable',
            icon='[color=#008000]󰯄[/color]'
            if state.is_enabled
            else '[color=#ffff00]󰯅[/color]',
            action=disable_ssh_service if state.is_enabled else enable_ssh_service,
        ),
    ]


@autorun(lambda state: state.ssh)
def ssh_title(state: SSHState) -> str:
    """Get the SSH title."""
    return (
        'SSH [color=#008000]󰧞[/color]'
        if state.is_active
        else 'SSH [color=#ffff00]󱃓[/color]'
    )


def check_is_ssh_active() -> None:
    """Check if the SSH service is active."""
    result = subprocess.run(
        ['/usr/bin/env', 'systemctl', 'is-active', 'ssh'],  # noqa: S603
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout.strip() == 'active':
        dispatch(SSHUpdateStateAction(is_active=True))
    else:
        dispatch(SSHUpdateStateAction(is_active=False))


def check_is_ssh_enabled() -> None:
    """Check if the SSH service is enabled."""
    result = subprocess.run(
        ['/usr/bin/env', 'systemctl', 'is-enabled', 'ssh'],  # noqa: S603
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout.strip() == 'enabled':
        dispatch(SSHUpdateStateAction(is_enabled=True))
    else:
        dispatch(SSHUpdateStateAction(is_enabled=False))


async def monitor_ssh_service() -> None:
    """Monitor the SSH service."""
    from cysystemd.async_reader import (  # pyright: ignore[reportMissingImports]
        AsyncJournalReader,
    )
    from cysystemd.reader import (  # pyright: ignore[reportMissingImports]
        JournalOpenMode,
        Rule,
    )

    reader = AsyncJournalReader()
    await reader.open(JournalOpenMode.SYSTEM)
    await reader.add_filter(Rule('_SYSTEMD_UNIT', 'init.scope'))
    await reader.seek_tail()

    check_is_ssh_enabled()
    check_is_ssh_active()

    while await reader.wait():
        async for record in reader:
            if 'MESSAGE' in record.data:
                if 'UNIT' in record.data and record.data['UNIT'] == 'ssh.service':
                    if (
                        'Started ssh.service - OpenBSD Secure Shell server'
                        in record.data['MESSAGE']
                    ):
                        dispatch(SSHUpdateStateAction(is_active=True))
                    elif (
                        'Stopped ssh.service - OpenBSD Secure Shell server'
                        in record.data['MESSAGE']
                    ):
                        dispatch(SSHUpdateStateAction(is_active=False))
                elif record.data['MESSAGE'] == 'Reloading.':
                    check_is_ssh_enabled()


def init_service() -> None:
    """Initialize the SSH service."""
    dispatch(
        RegisterSettingAppAction(
            menu_item=SubMenuItem(
                label='SSH',
                icon='󰣀',
                sub_menu=HeadlessMenu(
                    title=ssh_title,
                    items=ssh_items,
                ),
            ),
        ),
    )
    create_task(monitor_ssh_service())
