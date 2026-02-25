# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

from commands import (
    check_is_active,
    check_status,
    install_rpi_connect,
    sign_out,
    start_service,
    stop_service,
    uninstall_rpi_connect,
)

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
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from ubo_app.store.services.rpi_connect import (
        RPiConnectState,
    )

# Dynamic menu ID for dumb UI architecture
RPI_CONNECT_MENU_ID = 'rpi-connect:main'

_signin_process = None


async def _perform_signin() -> None:
    """Perform RPi Connect sign-in - extracted from SignInPage widget."""
    import asyncio
    import re
    import subprocess

    global _signin_process  # noqa: PLW0603
    try:
        _signin_process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'rpi-connect',
            'signin',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if _signin_process.stdout is None:
            return
        output = (await _signin_process.stdout.readline()).decode()
        regex = r'^Complete sign in by visiting (?P<url>[^\n]*)'
        match = re.search(regex, output)
        if match:
            url = match.group('url')
            store.dispatch(
                OpenApplicationAction(
                    application_id='rpi-connect:signin-page',
                    initialization_kwargs={'stage': '1', 'url': url},
                ),
            )
            await _signin_process.wait()
        else:
            logger.error(
                'RPi Connect: Failed to login: invalid output',
                extra={'output': output},
            )
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='RPi-Connect',
                        content='Failed to login: invalid output',
                        display_type=NotificationDisplayType.STICKY,
                        color='#D32F2F',
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
    except subprocess.CalledProcessError:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='RPi-Connect',
                    content='Failed to login: process error',
                    display_type=NotificationDisplayType.STICKY,
                    color='#D32F2F',
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
        raise
    finally:
        _signin_process = None
        await check_status()


def start_signin() -> None:
    """Start the sign-in process and open the sign-in page."""
    store.dispatch(
        OpenApplicationAction(
            application_id='rpi-connect:signin-page',
            initialization_kwargs={'stage': '0'},
        ),
    )
    create_task(_perform_signin())


def _register_rpi_connect_action_handlers() -> None:
    """Register action handlers for RPi Connect menu items."""
    from ubo_app.store.core.action_registry import register_action

    def _start_service() -> None:
        start_service()

    register_action('rpi-connect:start', _start_service, allow_reregister=True)
    register_action('rpi-connect:stop', stop_service, allow_reregister=True)
    register_action('rpi-connect:sign-out', sign_out, allow_reregister=True)
    register_action('rpi-connect:install', install_rpi_connect, allow_reregister=True)
    register_action(
        'rpi-connect:uninstall', uninstall_rpi_connect, allow_reregister=True,
    )

    register_action('rpi-connect:sign-in', start_signin, allow_reregister=True)

    def _open_qrcode() -> None:
        store.dispatch(
            OpenApplicationAction(application_id='rpi-connect:qrcode-page'),
        )

    register_action('rpi-connect:show-url', _open_qrcode, allow_reregister=True)


def _compute_rpi_connect_sub_heading(state: RPiConnectState) -> str:
    """Compute the sub_heading for RPi Connect menu from state."""
    if state.status:
        screen = state.status.screen_sharing_sessions
        shell = state.status.remote_shell_sessions
        screen_text = 'unavailable' if screen is None else f'{screen} sessions'
        shell_text = 'unavailable' if shell is None else f'{shell} sessions'
        return f'Screen sharing: {screen_text}\nRemote shell: {shell_text}'
    if state.is_downloading:
        return 'Downloading...'
    if state.is_installed:
        return 'Installed'
    return 'Not installed'


@store.autorun(lambda state: state.rpi_connect)
def update_rpi_connect_dynamic_menu(state: RPiConnectState) -> None:
    """Update the dynamic menu for RPi Connect (dumb UI architecture)."""
    _register_rpi_connect_action_handlers()

    items: list[MenuItemData] = []

    if not state.is_downloading:
        if state.is_installed:
            # Show URL if sessions are active
            if state.status and (
                state.status.screen_sharing_sessions is not None
                or state.status.remote_shell_sessions is not None
            ):
                items.append(
                    MenuItemData(
                        key='rpi-connect:show-url',
                        label='Show URL',
                        icon='󰐲',
                        action_id='rpi-connect:show-url',
                    ),
                )

            # Sign in/out actions
            if state.is_signed_in:
                items.append(
                    MenuItemData(
                        key='rpi-connect:sign-out',
                        label='Sign out',
                        icon='󰍃',
                        action_id='rpi-connect:sign-out',
                    ),
                )
            elif state.is_signed_in is False:
                items.append(
                    MenuItemData(
                        key='rpi-connect:sign-in',
                        label='Sign in',
                        icon='󰍂',
                        action_id='rpi-connect:sign-in',
                    ),
                )

            # Start/Stop action
            action_id = 'rpi-connect:stop' if state.is_active else 'rpi-connect:start'
            items.append(
                MenuItemData(
                    key='rpi-connect:toggle',
                    label='Stop' if state.is_active else 'Start',
                    icon='󰓛' if state.is_active else '󰐊',
                    action_id=action_id,
                ),
            )

        # Install/Uninstall action
        if state.is_installed is not None:
            install_label = (
                'Uninstall RPi-Connect' if state.is_installed else 'Install RPi-Connect'
            )
            install_action = (
                'rpi-connect:uninstall' if state.is_installed else 'rpi-connect:install'
            )
            items.append(
                MenuItemData(
                    key='rpi-connect:install-toggle',
                    label=install_label,
                    icon='󰇚',
                    action_id=install_action,
                ),
            )

    logger.debug(
        '[RPi Connect] Updating dynamic menu: is_installed=%s, is_active=%s',
        state.is_installed,
        state.is_active,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=RPI_CONNECT_MENU_ID,
            title='󰌕 RPi Connect',
            heading='RPi Connect',
            sub_heading=_compute_rpi_connect_sub_heading(state),
            items=tuple(items),
            placeholder='',
        ),
    )


def init_service() -> None:
    from ubo_app.store.core.action_registry import register_action

    def _open_rpi_connect_menu() -> bool:
        create_task(check_status())
        return True

    register_action('rpi-connect:open_menu', _open_rpi_connect_menu)
    store.dispatch(
        RegisterSettingAppAction(
            label='RPi Connect',
            icon='󰌕',
            action_id='rpi-connect:open_menu',
            category=SettingsCategory.REMOTE,
        ),
    )

    from ubo_app.store.core.view_registry import (
        create_settings_path_matcher,
        register_path_menu_matcher,
    )

    register_path_menu_matcher(
        'rpi-connect:settings',
        create_settings_path_matcher('rpi_connect:', RPI_CONNECT_MENU_ID),
    )

    create_task(check_is_active())
