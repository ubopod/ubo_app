# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

from commands import (
    check_status,
    connect,
    disconnect,
    install_tailscale,
    sign_out,
    uninstall_tailscale,
)

from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    OpenRenderAction,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPopAction,
    UpdateDynamicMenuAction,
    UpdateRenderPropsAction,
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
    from ubo_app.store.services.tailscale import TailscaleState

TAILSCALE_MENU_ID = 'tailscale:main'
ADMIN_CONSOLE_URL = 'https://login.tailscale.com/admin/machines'

_signin_process = None


async def _perform_signin() -> None:
    """Run `tailscale up`, scrape the login URL and show it as a QR code."""
    import asyncio
    import re
    import subprocess

    global _signin_process  # noqa: PLW0603
    try:
        _signin_process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'tailscale',
            'up',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if _signin_process.stdout is None:
            return
        regex = re.compile(r'(https://login\.tailscale\.com/\S+)')
        url = None
        while True:
            line = await _signin_process.stdout.readline()
            if not line:
                break
            match = regex.search(line.decode())
            if match:
                url = match.group(1)
                break

        if url:
            store.dispatch(
                UpdateRenderPropsAction(
                    kind='status',
                    next_kind='qr_code',
                    title='Tailscale Sign In',
                    props={'value': url, 'label': url},
                ),
            )
            await _signin_process.wait()
            store.dispatch(StackPopAction())
        else:
            await _signin_process.wait()
            store.dispatch(StackPopAction())
            if _signin_process.returncode != 0:
                logger.error('Tailscale: Failed to sign in')
                store.dispatch(
                    NotificationsAddAction(
                        notification=Notification(
                            title='Tailscale',
                            content='Failed to sign in',
                            display_type=NotificationDisplayType.STICKY,
                            color='#D32F2F',
                            icon='󰜺',
                            chime=Chime.FAILURE,
                        ),
                    ),
                )
    except subprocess.CalledProcessError:
        store.dispatch(StackPopAction())
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Tailscale',
                    content='Failed to sign in: process error',
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
    """Open the sign-in page and start the sign-in process."""
    store.dispatch(
        OpenRenderAction(
            kind='status',
            title='Tailscale Sign In',
            props={'text': 'Connecting...', 'text_font_size': 16},
        ),
    )
    create_task(_perform_signin())


def _open_admin_console() -> None:
    store.dispatch(
        OpenRenderAction(
            kind='qr_code',
            title='Tailscale',
            props={'value': ADMIN_CONSOLE_URL, 'label': ADMIN_CONSOLE_URL},
        ),
    )


def _register_tailscale_action_handlers() -> None:
    from ubo_app.store.core.action_registry import register_action

    register_action('tailscale:install', install_tailscale, allow_reregister=True)
    register_action('tailscale:uninstall', uninstall_tailscale, allow_reregister=True)
    register_action('tailscale:sign-in', start_signin, allow_reregister=True)
    register_action('tailscale:sign-out', sign_out, allow_reregister=True)
    register_action('tailscale:connect', connect, allow_reregister=True)
    register_action('tailscale:disconnect', disconnect, allow_reregister=True)
    register_action('tailscale:show-url', _open_admin_console, allow_reregister=True)


def _compute_tailscale_sub_heading(state: TailscaleState) -> str:
    if state.is_downloading:
        return 'Downloading...'
    if not state.is_installed:
        return 'Not installed'
    if state.backend_state == 'Running':
        return 'Connected'
    if state.backend_state == 'Stopped':
        return 'Disconnected'
    if state.backend_state == 'NeedsLogin':
        return 'Not signed in'
    return 'Installed'


_tailscale_actions_registered: list[bool] = [False]


@store.autorun(lambda state: state.tailscale)
def update_tailscale_dynamic_menu(state: TailscaleState) -> None:
    """Update the dynamic menu for Tailscale (dumb UI architecture)."""
    if not _tailscale_actions_registered[0]:
        _register_tailscale_action_handlers()
        _tailscale_actions_registered[0] = True

    items: list[MenuItemData] = []

    if not state.is_downloading:
        if state.is_installed:
            if state.backend_state == 'Running':
                items.append(
                    MenuItemData(
                        key='tailscale:show-url',
                        label='Show URL',
                        icon='󰐲',
                        action_id='tailscale:show-url',
                    ),
                )
                items.append(
                    MenuItemData(
                        key='tailscale:disconnect',
                        label='Disconnect',
                        icon='󰓛',
                        action_id='tailscale:disconnect',
                    ),
                )
                items.append(
                    MenuItemData(
                        key='tailscale:sign-out',
                        label='Sign out',
                        icon='󰍃',
                        action_id='tailscale:sign-out',
                    ),
                )
            elif state.backend_state == 'Stopped':
                items.append(
                    MenuItemData(
                        key='tailscale:connect',
                        label='Connect',
                        icon='󰐊',
                        action_id='tailscale:connect',
                    ),
                )
                items.append(
                    MenuItemData(
                        key='tailscale:sign-out',
                        label='Sign out',
                        icon='󰍃',
                        action_id='tailscale:sign-out',
                    ),
                )
            else:
                items.append(
                    MenuItemData(
                        key='tailscale:sign-in',
                        label='Sign in',
                        icon='󰍂',
                        action_id='tailscale:sign-in',
                    ),
                )

            items.append(
                MenuItemData(
                    key='tailscale:uninstall',
                    label='Uninstall Tailscale',
                    icon='󰇚',
                    action_id='tailscale:uninstall',
                ),
            )
        elif state.is_installed is False:
            items.append(
                MenuItemData(
                    key='tailscale:install',
                    label='Install Tailscale',
                    icon='󰇚',
                    action_id='tailscale:install',
                ),
            )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=TAILSCALE_MENU_ID,
            title='󰖂 Tailscale',
            heading='Tailscale',
            sub_heading=_compute_tailscale_sub_heading(state),
            items=tuple(items),
            placeholder='',
        ),
    )


def init_service() -> None:
    from ubo_app.store.core.action_registry import register_action

    def _open_tailscale_menu() -> bool:
        create_task(check_status())
        return True

    register_action('tailscale:open_menu', _open_tailscale_menu)
    store.dispatch(
        RegisterSettingAppAction(
            label='Tailscale',
            icon='󰖂',
            action_id='tailscale:open_menu',
            category=SettingsCategory.REMOTE,
        ),
    )

    from ubo_app.store.core.view_registry import (
        create_settings_path_matcher,
        register_path_menu_matcher,
    )

    register_path_menu_matcher(
        'tailscale:settings',
        create_settings_path_matcher('tailscale:', TAILSCALE_MENU_ID),
    )

    create_task(check_status())
