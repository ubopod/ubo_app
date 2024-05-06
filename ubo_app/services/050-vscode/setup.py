# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import subprocess
import time
from typing import TYPE_CHECKING

from checks import check_status
from constants import CODE_BINARY_PATH, CODE_BINARY_URL, DOWNLOAD_PATH
from login_page import LoginPage
from setup_page import SetupPage
from ubo_gui.constants import DANGER_COLOR
from ubo_gui.menu.types import ActionItem, ApplicationItem, HeadedMenu

from ubo_app.constants import INSTALLATION_PATH
from ubo_app.store import autorun, dispatch
from ubo_app.store.main import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.vscode import (
    VSCodeDoneDownloadingAction,
    VSCodeStartDownloadingAction,
    VSCodeState,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Callable


def download_code() -> None:
    CODE_BINARY_PATH.unlink(missing_ok=True)
    dispatch(VSCodeStartDownloadingAction())

    async def act() -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'curl',
                '-Lk',
                CODE_BINARY_URL,
                '--output',
                DOWNLOAD_PATH,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await process.wait()
            process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'tar',
                'zxf',
                DOWNLOAD_PATH,
                '-C',
                INSTALLATION_PATH,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await process.wait()
        except subprocess.CalledProcessError:
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
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
        dispatch(VSCodeDoneDownloadingAction())
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
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            await process.wait()
            await check_status()
        except subprocess.CalledProcessError:
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='VSCode',
                        content='Failed to logout',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )

    create_task(act())


@autorun(
    lambda state: state.vscode,
    comparator=lambda state: (
        state.vscode.is_binary_installed,
        state.vscode.is_logged_in,
        state.vscode.is_downloading,
    ),
)
def vscode_menu(state: VSCodeState) -> HeadedMenu:
    if state.last_update_timestamp < time.time() - 10:
        create_task(check_status())
        return HeadedMenu(
            title='󰨞VSCode',
            heading='󰔟Checking...',
            sub_heading='',
            items=[],
        )

    actions = []
    if not state.is_downloading:
        if state.is_binary_installed:
            if state.is_logged_in:
                actions.extend(
                    [
                        ApplicationItem(
                            label='Setup Tunnel',
                            icon='󰒔',
                            application=SetupPage,
                        ),
                        ActionItem(
                            label='Logout',
                            icon='󰍃',
                            action=logout,
                        ),
                    ],
                )
            else:
                actions.append(
                    ApplicationItem(
                        label='Login',
                        icon='󰍂',
                        application=LoginPage,
                    ),
                )

        actions.append(
            ActionItem(
                label='Update Code CLI'
                if state.is_binary_installed
                else 'Download Code CLI',
                icon='󰇚',
                action=download_code,
            ),
        )

    return HeadedMenu(
        title='󰨞VSCode',
        heading='Setup VSCode Tunnel',
        sub_heading='Downloading...' if state.is_downloading else '',
        items=actions,
    )


def generate_vscode_menu() -> Callable[[], HeadedMenu]:
    create_task(check_status())
    return vscode_menu


async def init_service() -> None:
    dispatch(
        RegisterSettingAppAction(
            menu_item=ActionItem(label='VSCode', icon='󰨞', action=generate_vscode_menu),
            category=SettingsCategory.REMOTE,
        ),
    )
    while True:
        await asyncio.sleep(3)
        await check_status()
