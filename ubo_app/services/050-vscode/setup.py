# ruff: noqa: D100, D103
from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING

from commands import check_status, restart, uninstall_service
from constants_ import CODE_BINARY_PATH, CODE_BINARY_URL, CODE_DOWNLOAD_PATH

from ubo_app.colors import DANGER_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    OpenRenderAction,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPopAction,
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
)
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
                OpenRenderAction(
                    kind='qr_code',
                    title='VSCode Login',
                    props={'value': url, 'label': code},
                ),
            )
            await _login_process.wait()
            # Pop both the QR view and the "Logging in..." status view that
            # `start_login` pushed, returning to the VSCode menu.
            store.dispatch(StackPopAction(count=2))
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
        OpenRenderAction(
            kind='status',
            title='VSCode Login',
            props={'text': 'Logging in...', 'text_font_size': 32},
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
    from ubo_app.store.core.action_registry import register_action

    register_action('vscode:download', download_code, allow_reregister=True)
    register_action('vscode:logout', logout, allow_reregister=True)
    register_action('vscode:login', start_login, allow_reregister=True)


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


_vscode_show_url_action_ids: list[str] = []


@store.autorun(lambda state: state.vscode)
def update_vscode_dynamic_menu(state: VSCodeState) -> None:
    """Update the dynamic menu for VSCode (dumb UI architecture)."""
    _register_vscode_action_handlers()

    # Register show-url action dynamically based on current status
    if state.status and state.status.is_running and state.status.name:
        from ubo_app.store.core.action_registry import (
            register_action,
            unregister_action,
        )

        # Unregister previously tracked show-url actions
        for old_id in _vscode_show_url_action_ids:
            unregister_action(old_id)
        _vscode_show_url_action_ids.clear()

        action_id = f'vscode:show-url:{state.status.name}'

        def _make_show_url_handler(name: str) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(
                    OpenRenderAction(
                        kind='qr_code',
                        title='VSCode Remote',
                        props={
                            'value': f'{CODE_TUNNEL_URL_PREFIX}{name}',
                            'label': f'{CODE_TUNNEL_URL_PREFIX}{name}',
                        },
                    ),
                )

            return _handler

        register_action(action_id, _make_show_url_handler(state.status.name))
        _vscode_show_url_action_ids.append(action_id)

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
            title='󰨞 VSCode',
            heading='VSCode Remote Tunnel',
            sub_heading=_compute_vscode_sub_heading(state),
            items=tuple(items),
            placeholder='',
        ),
    )


async def _monitor_status(end_event: asyncio.Event) -> None:
    while not end_event.is_set():
        await check_status()
        await asyncio.sleep(1)


async def init_service() -> Subscriptions:
    from ubo_app.store.core.action_registry import register_action

    def _open_vscode_menu() -> bool:
        create_task(check_status())
        return True

    register_action('vscode:open_menu', _open_vscode_menu)
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
