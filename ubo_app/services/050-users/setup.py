"""SSH service module."""

from __future__ import annotations

import asyncio
import datetime
from asyncio import Future
from typing import TYPE_CHECKING

from ubo_gui.menu.types import (
    HeadedMenu,
    HeadlessMenu,
    Menu,
    SubMenuItem,
)

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.services.users import (
    UsersCreateUserAction,
    UsersCreateUserEvent,
    UsersDeleteUserAction,
    UsersDeleteUserEvent,
    UsersResetPasswordAction,
    UsersResetPasswordEvent,
    UsersSetUsersAction,
    UsersState,
    UserState,
)
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.async_ import create_task
from ubo_app.utils.bus_provider import get_system_bus
from ubo_app.utils.dbus_interfaces import AccountsInterface, UserInterface
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


async def create_account() -> None:
    """Create a system user account."""
    result = await send_command('users', 'create', has_output=True)
    if not result:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Failed to create account',
                    content='An error occurred while creating the user account.',
                    importance=Importance.MEDIUM,
                    icon='󰀅',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                ),
            ),
        )

        return
    username, password = result.split(':')
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='Account Info',
                content='[size=18dp][b]host:[/b] {{hostname}}\n'
                f'[b]user:[/b] {username}\n[b]pass:[/b] {password}[/size]',
                importance=Importance.MEDIUM,
                icon='󰀈',
                display_type=NotificationDisplayType.STICKY,
                extra_information=ReadableInformation(
                    text="""\
Note that in order to make ssh works for you, we had to make sure password \
authentication for ssh server is enabled, you may want to disable it later.""",
                    picovoice_text="""\
Note that in order to make ssh works for you, we had to make sure password \
authentication for {ssh|EH S EH S EY CH} server is enabled, you may want to disable it \
later.""",
                ),
                color=SUCCESS_COLOR,
            ),
        ),
    )


async def delete_account(event: UsersDeleteUserEvent) -> None:
    """Delete a user account."""
    loop = asyncio.get_running_loop()
    notification_future: Future[None] = loop.create_future()
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='qrcode',
                icon='󰀕',
                title='Users',
                content=f'Delete user "{event.id}"?',
                display_type=NotificationDisplayType.STICKY,
                is_read=True,
                extra_information=ReadableInformation(
                    text='This will delete the system user account and its home '
                    'directory.',
                ),
                expiration_timestamp=datetime.datetime.now(tz=datetime.UTC),
                actions=[
                    NotificationActionItem(
                        action=lambda: loop.call_soon_threadsafe(
                            notification_future.set_result,
                            None,
                        )
                        and None,
                        icon='󰀍',
                        dismiss_notification=True,
                    ),
                ],
                show_dismiss_action=False,
                dismiss_on_close=True,
                on_close=lambda: loop.call_soon_threadsafe(notification_future.cancel),
            ),
        ),
    )

    await notification_future

    await send_command('users', 'delete', event.id)
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='Users',
                content=f'User "{event.id}" deleted.',
                importance=Importance.MEDIUM,
                icon='󰀕',
                display_type=NotificationDisplayType.FLASH,
            ),
        ),
    )


async def reset_password(event: UsersResetPasswordEvent) -> None:
    """Reset the password of a user account."""
    result = await send_command('users', 'reset_password', event.id, has_output=True)
    if not result:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Failed to reset password',
                    content='An error occurred while resetting password for '
                    f'"{event.id}".',
                    importance=Importance.MEDIUM,
                    icon='󰀅',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                ),
            ),
        )

        return
    username, password = result.split(':')
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='Account Info',
                content='[size=18dp][b]host:[/b] {{hostname}}\n'
                f'[b]user:[/b] {username}\n[b]pass:[/b] {password}[/size]',
                importance=Importance.MEDIUM,
                icon='󰀈',
                display_type=NotificationDisplayType.STICKY,
                extra_information=ReadableInformation(
                    text="""\
Note that in order to make ssh works for you, we had to make sure password \
authentication for ssh server is enabled, you may want to disable it later.""",
                    picovoice_text="""\
Note that in order to make ssh works for you, we had to make sure password \
authentication for {ssh|EH S EH S EY CH} server is enabled, you may want to disable it \
later.""",
                ),
                color=SUCCESS_COLOR,
            ),
        ),
    )


@store.autorun(lambda state: state.users)
def users_menu(state: UsersState) -> Menu:
    """Get the SSH menu items."""
    if state.users is None:
        return HeadedMenu(
            title='󰡉Users',
            heading='Loading...',
            sub_heading='Please wait...',
            items=[],
        )
    return HeadlessMenu(
        title='󰡉Users',
        items=[
            UboDispatchItem(
                label='Add',
                icon='󰀔',
                store_action=UsersCreateUserAction(),
                background_color=WARNING_COLOR,
            ),
            *[
                SubMenuItem(
                    key=user.id,
                    label=user.id,
                    icon='󰀄',
                    sub_menu=HeadlessMenu(
                        title=user.id,
                        items=[
                            UboDispatchItem(
                                label='Reset Password',
                                icon='󰯄',
                                store_action=UsersResetPasswordAction(id=user.id),
                                background_color=WARNING_COLOR,
                            ),
                            UboDispatchItem(
                                label='Delete',
                                icon='󰀕',
                                store_action=UsersDeleteUserAction(id=user.id),
                                background_color=DANGER_COLOR,
                            ),
                        ],
                    ),
                )
                for user in state.users
            ],
        ],
    )


async def init_service() -> Subscriptions:
    """Initialize the Users service."""
    store.dispatch(
        RegisterSettingAppAction(
            priority=1,
            category=SettingsCategory.SYSTEM,
            menu_item=SubMenuItem(
                label='Users',
                icon='󰡉',
                sub_menu=users_menu,
            ),
        ),
    )

    bus = get_system_bus()
    accounts_service = AccountsInterface.new_proxy(
        bus=bus,
        service_name='org.freedesktop.Accounts',
        object_path='/org/freedesktop/Accounts',
    )

    async def get_users() -> list[UserState]:
        paths = await accounts_service.list_cached_users()
        return [
            UserState(
                id=(
                    user_name := await UserInterface.new_proxy(
                        bus=bus,
                        service_name='org.freedesktop.Accounts',
                        object_path=path,
                    ).user_name
                ),
                is_removable=user_name != 'ubo',
            )
            for path in paths
        ]

    store.dispatch(UsersSetUsersAction(users=await get_users()))

    async def monitor_user_added() -> None:
        async for path in accounts_service.user_added:
            logger.info('User added', extra={'path': path})
            store.dispatch(UsersSetUsersAction(users=await get_users()))

    async def monitor_user_deleted() -> None:
        async for path in accounts_service.user_deleted:
            logger.info('User deleted', extra={'path': path})
            store.dispatch(UsersSetUsersAction(users=await get_users()))

    return [
        store.subscribe_event(UsersCreateUserEvent, create_account),
        store.subscribe_event(UsersDeleteUserEvent, delete_account),
        store.subscribe_event(UsersResetPasswordEvent, reset_password),
        create_task(monitor_user_added()).cancel,
        create_task(monitor_user_deleted()).cancel,
    ]
