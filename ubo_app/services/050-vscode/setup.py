# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import pathlib
import subprocess
from typing import TYPE_CHECKING

from commands import check_status, restart, uninstall_service
from constants_ import CODE_BINARY_PATH, CODE_BINARY_URL, CODE_DOWNLOAD_PATH
from kivy.lang.builder import Builder
from kivy.properties import StringProperty
from login_page import LoginPage
from ubo_gui.menu.types import ActionItem, ApplicationItem, HeadedMenu

from ubo_app.colors import DANGER_COLOR
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
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
from ubo_app.store.ubo_actions import UboApplicationItem, register_application
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import UboPageWidget
from ubo_app.utils.log_process import log_async_process


class _VSCodeQRCodePage(UboPageWidget):
    url = StringProperty()


register_application(application=_VSCodeQRCodePage, application_id='vscode:qrcode-page')
register_application(application=LoginPage, application_id='vscode:login-page')

CODE_TUNNEL_URL_PREFIX = 'https://vscode.dev/tunnel/'

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.utils.types import Subscriptions


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
            UboApplicationItem(
                label='Login',
                icon='󰍂',
                application_id='vscode:login-page',
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
    store.dispatch(
        RegisterSettingAppAction(
            menu_item=ActionItem(label='VSCode', icon='󰨞', action=generate_vscode_menu),
            category=SettingsCategory.REMOTE,
        ),
    )

    await check_status()

    end_event = asyncio.Event()
    create_task(_monitor_status(end_event))

    return [
        store.subscribe_event(VSCodeRestartEvent, restart),
        end_event.set,
    ]


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('vscode_qrcode_page.kv')
    .resolve()
    .as_posix(),
)
