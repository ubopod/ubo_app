"""SSH service module."""

from __future__ import annotations

import asyncio
import time
from asyncio import Future
from typing import TYPE_CHECKING

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.callback_registry import register_auto_callback
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
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
from ubo_app.utils.async_ import create_task
from ubo_app.utils.bus_provider import get_system_bus
from ubo_app.utils.dbus_interfaces import AccountsInterface, UserInterface
from ubo_app.utils.server import send_command

# Dynamic menu ID for dumb UI architecture
USERS_MENU_ID = 'users:main'

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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
                expiration_timestamp=time.time(),
                actions=[
                    create_notification_action(
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
                on_close_id=register_auto_callback(
                    lambda: loop.call_soon_threadsafe(notification_future.cancel),
                ),
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


def _register_users_action_handlers() -> None:
    """Register action handlers for Users menu items."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
    )

    # Only register once
    if 'users:add' in get_registered_actions():
        return

    def _add_user() -> None:
        store.dispatch(UsersCreateUserAction())

    register_action('users:add', _add_user)


def _register_user_detail_actions(users: Sequence[UserState]) -> None:
    """Register action handlers and dynamic menus for each user's detail page."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
        unregister_action,
    )

    # Unregister old user-specific actions
    for action_id in list(get_registered_actions()):
        if action_id.startswith(
            ('users:open-user:', 'users:reset-password:', 'users:delete:'),
        ):
            unregister_action(action_id)

    for user in users:
        uid = user.id

        def _make_open_handler(user_id: str) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(StackPushMenuAction(menu_key=f'users:user:{user_id}'))

            return _handler

        def _make_reset_handler(user_id: str) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(UsersResetPasswordAction(id=user_id))

            return _handler

        def _make_delete_handler(user_id: str) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(UsersDeleteUserAction(id=user_id))

            return _handler

        register_action(f'users:open-user:{uid}', _make_open_handler(uid))
        register_action(f'users:reset-password:{uid}', _make_reset_handler(uid))
        register_action(f'users:delete:{uid}', _make_delete_handler(uid))

        # Create dynamic menu for user detail page
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=f'users:user:{uid}',
                title=uid,
                items=(
                    MenuItemData(
                        key=f'users:reset-password:{uid}',
                        label='Reset Password',
                        icon='󰯄',
                        action_id=f'users:reset-password:{uid}',
                        background_color=WARNING_COLOR,
                    ),
                    MenuItemData(
                        key=f'users:delete:{uid}',
                        label='Delete',
                        icon='󰀕',
                        action_id=f'users:delete:{uid}',
                        background_color=DANGER_COLOR,
                    ),
                ),
            ),
        )


@store.autorun(lambda state: state.users)
def update_users_dynamic_menu(state: UsersState) -> None:
    """Update the dynamic menu for Users (dumb UI architecture)."""
    _register_users_action_handlers()

    items: list[MenuItemData] = []

    if state.users is not None:
        _register_user_detail_actions(state.users)

        # Add user action
        items.append(
            MenuItemData(
                key='users:add',
                label='Add',
                icon='󰀔',
                action_id='users:add',
                background_color=WARNING_COLOR,
            ),
        )

        # List existing users (clicking opens user submenu)
        items.extend(
            MenuItemData(
                key=f'users:user:{user.id}',
                label=user.id,
                icon='󰀄',
                action_id=f'users:open-user:{user.id}',
            )
            for user in state.users
        )

    logger.debug(
        '[Users Service] Updating dynamic menu: %d users',
        len(state.users) if state.users else 0,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=USERS_MENU_ID,
            title='Users',
            heading='Loading...' if state.users is None else None,
            sub_heading='Please wait...' if state.users is None else None,
            items=tuple(items),
            placeholder='Loading...' if state.users is None else '',
        ),
    )


async def init_service() -> Subscriptions:
    """Initialize the Users service."""
    store.dispatch(
        RegisterSettingAppAction(
            priority=1,
            category=SettingsCategory.SYSTEM,
            label='Users',
            icon='󰡉',
        ),
    )

    # Register path matcher for Users menu navigation
    from ubo_app.store.core.view_registry import register_path_menu_matcher

    def _users_path_matcher(path: tuple[str, ...]) -> str | None:
        if len(path) >= 4 and path[3] == 'users:':  # noqa: PLR2004
            if len(path) == 4:  # noqa: PLR2004
                return USERS_MENU_ID
            # User detail page: path[4] is 'users:user:{username}'
            if len(path) == 5:  # noqa: PLR2004
                return path[4]
        return None

    register_path_menu_matcher('users:settings', _users_path_matcher)

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
