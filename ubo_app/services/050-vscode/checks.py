# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Literal, TypedDict

from constants import CODE_BINARY_PATH
from debouncer import DebounceOptions, debounce
from ubo_gui.constants import DANGER_COLOR

from ubo_app.logging import logger
from ubo_app.store import dispatch
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.vscode import (
    VSCodeSetStatusAction,
    VSCodeStatus,
)


class TunnelStatus(TypedDict):
    tunnel: Literal['Connected', 'Disconnected']
    name: str | None


class TunnelServiceStatus(TypedDict):
    service_installed: bool
    tunnel: TunnelStatus


@debounce(
    wait=1,
    options=DebounceOptions(leading=True, trailing=False, time_window=1),
)
async def check_status() -> None:
    is_binary_installed = CODE_BINARY_PATH.exists()
    status_data: TunnelServiceStatus | None = None
    is_logged_in = False

    try:
        if is_binary_installed:
            process = await asyncio.create_subprocess_exec(
                CODE_BINARY_PATH.as_posix(),
                'tunnel',
                '--accept-server-license-terms',
                'status',
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            await process.wait()
            if process.stdout and process.returncode == 0:
                output = await process.stdout.read()
                status_data = json.loads(output)
    except subprocess.CalledProcessError:
        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='VSCode',
                    content='Failed to get status: "status" subcommand',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
    else:
        try:
            if is_binary_installed:
                process = await asyncio.create_subprocess_exec(
                    CODE_BINARY_PATH.as_posix(),
                    'tunnel',
                    '--accept-server-license-terms',
                    'user',
                    'show',
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                await process.wait()
                is_logged_in = process.returncode == 0
        except subprocess.CalledProcessError:
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='VSCode',
                        content='Failed to get status: "user show" subcommand',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
    logger.debug(
        'Checked VSCode Tunnel Status',
        extra={
            'status': status_data,
            'is_logged_in': is_logged_in,
            'is_binary_installed': is_binary_installed,
        },
    )
    dispatch(
        VSCodeSetStatusAction(
            is_binary_installed=is_binary_installed,
            is_logged_in=is_logged_in,
            status=None
            if status_data is None
            else VSCodeStatus(
                is_service_installed=status_data['service_installed'],
                is_running=status_data['tunnel'] is not None
                and status_data['tunnel']['tunnel'] == 'Connected',
                name=None
                if status_data['tunnel'] is None
                else status_data['tunnel']['name'],
            ),
        ),
    )
