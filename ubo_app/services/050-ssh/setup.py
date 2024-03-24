"""SSH service module."""

from __future__ import annotations

from ubo_gui.menu.types import (
    ActionItem,
    ApplicationItem,
    HeadedMenu,
    HeadlessMenu,
    SubMenuItem,
)
from ubo_gui.prompt import PromptWidget

from ubo_app.store import dispatch
from ubo_app.store.main import RegisterSettingAppAction
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.server import send_command


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


def init_service() -> None:
    """Initialize the SSH service."""

    def create_ssh_account() -> None:
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

    dispatch(
        RegisterSettingAppAction(
            menu_item=SubMenuItem(
                label='SSH',
                icon='󰣀',
                sub_menu=HeadlessMenu(
                    title='SSH',
                    items=[
                        SubMenuItem(
                            label='Setup',
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
                    ],
                ),
            ),
        ),
    )
