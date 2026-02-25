# ruff: noqa: D100, D103
from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from commands import check_status, restart, uninstall_service
from constants_ import CODE_BINARY_PATH, CODE_BINARY_URL, CODE_DOWNLOAD_PATH
from ubo_gui.menu.types import ActionItem, ApplicationItem, HeadedMenu

from ubo_app.colors import DANGER_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    OpenApplicationAction,
    RegisterSettingAppAction,
    SettingsCategory,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.vscode import (
    VSCodeDoneDownloadingAction,
    VSCodeRestartEvent,
    VSCodeStartDownloadingAction,
    VSCodeState,
    VSCodeStatus,
)
from ubo_app.store.ubo_actions import UboApplicationItem
from ubo_app.utils.async_ import create_task
from ubo_app.utils.log_process import log_async_process

# Dynamic menu ID for dumb UI architecture
VSCODE_MENU_ID = 'vscode:main'

CODE_TUNNEL_URL_PREFIX = 'https://vscode.dev/tunnel/'

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.utils.types import Subscriptions


_login_process: asyncio.subprocess.Process | None = None


async def _perform_login() -> None:
    """Perform VSCode login - business logic extracted from LoginPage widget."""
    import re

    from commands import install_service

    global _login_process  # noqa: PLW0603
    try:
        _login_process = await asyncio.create_subprocess_exec(
            CODE_BINARY_PATH.as_posix(),
            'tunnel',
            '--accept-server-license-terms',
            'user',
            'login',
            '--provider',
            'github',
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if _login_process.stdout is None:
            return
        output = (await _login_process.stdout.readline()).decode()
        regex = (
            r'To grant access to the server, please log into (?P<url>[^\s]*) and '
            r'use code (?P<code>[^\s]*)'
        )
        match = re.search(regex, output)
        if match:
            url = match.group('url')
            code = match.group('code')
            store.dispatch(
                OpenApplicationAction(
                    application_id='vscode:login-page',
                    initialization_kwargs={'stage': '1', 'url': url, 'code': code},
                ),
            )
            await _login_process.wait()
        else:
            logger.error(
                'VSCode: Failed to login: invalid output',
                extra={'output': output},
            )
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id='vscode:login',
                        title='VSCode',
                        content='Failed to login: invalid output',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
    except subprocess.CalledProcessError:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='vscode:error:login',
                    title='VSCode',
                    content='Failed to login: process error',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
        raise
    finally:
        _login_process = None
        await install_service()


def start_login() -> None:
    """Start the login process and open the login page."""
    store.dispatch(
        OpenApplicationAction(
            application_id='vscode:login-page',
            initialization_kwargs={'stage': '0'},
        ),
    )
    create_task(_perform_login())


def download_code() -> None:
    CODE_BINARY_PATH.unlink(missing_ok=True)
    store.dispatch(VSCodeStartDownloadingAction())

    async def act() -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'curl',
                '-Lk',
                CODE_BINARY_URL,
                '--output',
                CODE_DOWNLOAD_PATH,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            store.dispatch(
                await log_async_process(process, message='Downloading VSCode'),
            )

            process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'tar',
                'zxf',
                CODE_DOWNLOAD_PATH,
                '-C',
                CODE_BINARY_PATH.parent,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            store.dispatch(await log_async_process(process, message='Unpacking VSCode'))

            process = await asyncio.create_subprocess_exec(
                CODE_BINARY_PATH,
                'version',
                'use',
                'stable',
                '--install-dir',
                CODE_BINARY_PATH,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            store.dispatch(
                await log_async_process(process, message='Installing VSCode'),
            )
        except subprocess.CalledProcessError:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id='vscode:download',
                        title='VSCode',
                        content='Failed to download',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
            CODE_BINARY_PATH.unlink(missing_ok=True)
            raise
        finally:
            CODE_DOWNLOAD_PATH.unlink(missing_ok=True)
            store.dispatch(VSCodeDoneDownloadingAction())
            await check_status()

    create_task(act())


def logout() -> None:
    async def act() -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                CODE_BINARY_PATH.as_posix(),
                'tunnel',
                '--accept-server-license-terms',
                'user',
                'logout',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            await uninstall_service()
        except subprocess.CalledProcessError:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id='vscode:logout',
                        title='VSCode',
                        content='Failed to logout',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
            raise

    create_task(act())


def status_based_actions(status: VSCodeStatus) -> list[ActionItem | ApplicationItem]:
    actions = []

    if status.is_running:
        actions.append(
            UboApplicationItem(
                label='Show URL',
                icon='󰐲',
                application_id='vscode:qrcode-page',
                initialization_kwargs={'url': f'{CODE_TUNNEL_URL_PREFIX}{status.name}'},
            ),
        )
    return actions


def login_actions(*, is_logged_in: bool | None) -> list[ActionItem | ApplicationItem]:
    actions = []
    if is_logged_in:
        actions.extend(
            [
                ActionItem(
                    label='Logout',
                    icon='󰍃',
                    action=logout,
                ),
            ],
        )
    elif is_logged_in is False:
        actions.append(
            ActionItem(
                label='Login',
                icon='󰍂',
                action=start_login,
            ),
        )
    return actions


def generate_actions(state: VSCodeState) -> list[ActionItem | ApplicationItem]:
    actions = []
    if not state.is_pending and not state.is_downloading:
        if state.is_binary_installed:
            if state.is_logged_in and state.status:
                actions.extend(status_based_actions(state.status))
            actions.extend(login_actions(is_logged_in=state.is_logged_in))

        actions.append(
            ActionItem(
                label='Redownload Code'
                if state.is_binary_installed
                else 'Download Code CLI',
                icon='󰇚',
                action=download_code,
            ),
        )
    return actions


def _generate_dynamic_menu_items(state: VSCodeState) -> list[MenuItemData]:
    """Generate MenuItemData for the dynamic menu (dumb UI architecture)."""
    items: list[MenuItemData] = []

    if state.is_pending or state.is_downloading:
        return items  # No actions during pending/downloading

    if state.is_binary_installed:
        # Show URL if running
        if state.is_logged_in and state.status and state.status.is_running:
            items.append(
                MenuItemData(
                    key='vscode:show-url',
                    label='Show URL',
                    icon='󰐲',
                    action_id=f'vscode:show-url:{state.status.name}',
                ),
            )

        # Login/Logout actions
        if state.is_logged_in:
            items.append(
                MenuItemData(
                    key='vscode:logout',
                    label='Logout',
                    icon='󰍃',
                    action_id='vscode:logout',
                ),
            )
        elif state.is_logged_in is False:
            items.append(
                MenuItemData(
                    key='vscode:login',
                    label='Login',
                    icon='󰍂',
                    action_id='vscode:login',
                ),
            )

    # Download/Redownload action
    download_label = (
        'Redownload Code' if state.is_binary_installed else 'Download Code CLI'
    )
    items.append(
        MenuItemData(
            key='vscode:download',
            label=download_label,
            icon='󰇚',
            action_id='vscode:download',
        ),
    )

    return items


def _register_vscode_action_handlers() -> None:
    """Register action handlers for VSCode menu items."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
    )

    # Only register once
    if 'vscode:download' in get_registered_actions():
        return

    register_action('vscode:download', download_code)
    register_action('vscode:logout', logout)
    register_action('vscode:login', start_login)


def _compute_vscode_sub_heading(state: VSCodeState) -> str:
    """Compute the sub_heading for VSCode menu from state."""
    if state.is_pending:
        return ''
    if state.status:
        if state.status.is_running:
            if state.status.name:
                return f'Service is running, name:\n{state.status.name}'
            return 'Service is running\nWaiting for name...'
        if not state.status.is_service_installed:
            return 'Service not installed'
        return 'Service installed but not running'
    if state.is_downloading:
        return 'Downloading...'
    if not state.is_binary_installed:
        return 'Code CLI not installed'
    if state.is_logged_in is None:
        return 'Checking status...'
    if state.is_logged_in is False:
        return 'Needs authentication'
    return 'Unknown status'


@store.autorun(lambda state: state.vscode)
def update_vscode_dynamic_menu(state: VSCodeState) -> None:
    """Update the dynamic menu for VSCode (dumb UI architecture)."""
    _register_vscode_action_handlers()

    # Register show-url action dynamically based on current status
    if state.status and state.status.is_running and state.status.name:
        from ubo_app.store.core.action_registry import (
            get_registered_actions,
            register_action,
            unregister_action,
        )

        action_id = f'vscode:show-url:{state.status.name}'
        if action_id not in get_registered_actions():
            # Unregister old show-url actions
            for old_action_id in get_registered_actions():
                if old_action_id.startswith('vscode:show-url:'):
                    unregister_action(old_action_id)

            def _make_show_url_handler(name: str) -> Callable[[], None]:
                def _handler() -> None:
                    store.dispatch(
                        OpenApplicationAction(
                            application_id='vscode:qrcode-page',
                            initialization_kwargs={
                                'url': f'{CODE_TUNNEL_URL_PREFIX}{name}',
                            },
                        ),
                    )

                return _handler

            register_action(action_id, _make_show_url_handler(state.status.name))

    items = _generate_dynamic_menu_items(state)

    logger.debug(
        '[VSCode Service] Updating dynamic menu: '
        'is_binary_installed=%s, is_logged_in=%s',
        state.is_binary_installed,
        state.is_logged_in,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=VSCODE_MENU_ID,
            title='VSCode',
            heading='VSCode Remote Tunnel',
            sub_heading=_compute_vscode_sub_heading(state),
            items=tuple(items),
            placeholder='',
        ),
    )


@store.autorun(lambda state: state.vscode)
def vscode_menu(state: VSCodeState) -> HeadedMenu:
    actions = generate_actions(state)

    status = ''
    if state.is_pending:
        status = '[size=48dp][/size]'
    elif state.status:
        if state.status.is_running:
            if state.status.name:
                status = f'Service is running, name:\n{state.status.name}'
            else:
                status = 'Service is running\nWaiting for name...'
        elif not state.status.is_service_installed:
            status = 'Service not installed'
        else:
            status = 'Service installed but not running'
    elif state.is_downloading:
        status = 'Downloading...'
    elif not state.is_binary_installed:
        status = 'Code CLI not installed'
    elif state.is_logged_in is None:
        status = 'Checking status...'
    elif state.is_logged_in is False:
        status = 'Needs authentication'
    else:
        status = 'Unknown status'

    return HeadedMenu(
        title='󰨞VSCode',
        heading='VSCode Remote Tunnel',
        sub_heading=status,
        items=actions,
        placeholder='',
    )


def generate_vscode_menu() -> Callable[[], HeadedMenu]:
    create_task(check_status())
    return vscode_menu


async def _monitor_status(end_event: asyncio.Event) -> None:
    while not end_event.is_set():
        await check_status()
        await asyncio.sleep(1)


async def init_service() -> Subscriptions:
    from ubo_app.store.core.action_registry import register_action

    register_action('vscode:open_menu', generate_vscode_menu)
    store.dispatch(
        RegisterSettingAppAction(
            label='VSCode',
            icon='󰨞',
            action_id='vscode:open_menu',
            category=SettingsCategory.REMOTE,
        ),
    )

    from ubo_app.store.core.view_registry import (
        create_settings_path_matcher,
        register_path_menu_matcher,
    )

    register_path_menu_matcher(
        'vscode:settings',
        create_settings_path_matcher('vscode:', VSCODE_MENU_ID),
    )

    await check_status()

    end_event = asyncio.Event()
    create_task(_monitor_status(end_event))

    return [
        store.subscribe_event(VSCodeRestartEvent, restart),
        end_event.set,
    ]
