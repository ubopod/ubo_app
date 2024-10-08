# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
from typing import Literal, TypedDict

from _constants import CODE_BINARY_PATH
from debouncer import DebounceOptions, debounce
from ubo_gui.constants import DANGER_COLOR

from ubo_app.logging import logger
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.vscode import (
    VSCodeSetPendingAction,
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
            await asyncio.wait_for(process.wait(), timeout=3)
            if process.returncode is None:
                process.kill()
            if process.stdout and process.returncode == 0:
                output = await process.stdout.read()
                status_data = json.loads(output)
    except (subprocess.CalledProcessError, TimeoutError):
        store.dispatch(
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
                await asyncio.wait_for(process.wait(), timeout=3)
                if process.returncode is None:
                    process.kill()
                is_logged_in = process.returncode == 0
        except (subprocess.CalledProcessError, TimeoutError):
            store.dispatch(
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
    store.dispatch(
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


async def set_name() -> None:
    store.dispatch(VSCodeSetPendingAction())
    try:
        hostname = socket.gethostname()
        process = await asyncio.create_subprocess_exec(
            CODE_BINARY_PATH,
            'tunnel',
            '--accept-server-license-terms',
            'rename',
            hostname,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=3)
        if process.returncode is None:
            process.kill()
    except (subprocess.CalledProcessError, TimeoutError):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='VSCode',
                    content='Failed to setup: renaming the tunnel',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
    finally:
        await check_status()


async def install_service() -> None:
    store.dispatch(VSCodeSetPendingAction())
    try:
        process = await asyncio.create_subprocess_exec(
            CODE_BINARY_PATH,
            'tunnel',
            '--accept-server-license-terms',
            'service',
            'install',
        )
        await asyncio.wait_for(process.wait(), timeout=3)
        if process.returncode is None:
            process.kill()
    except (subprocess.CalledProcessError, TimeoutError):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='VSCode',
                    content='Failed to setup: installing service',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
    finally:
        await check_status()


async def uninstall_service() -> None:
    store.dispatch(VSCodeSetPendingAction())
    try:
        process = await asyncio.create_subprocess_exec(
            CODE_BINARY_PATH,
            'tunnel',
            '--accept-server-license-terms',
            'service',
            'uninstall',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=3)
        if process.returncode is None:
            process.kill()
    except (subprocess.CalledProcessError, TimeoutError):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='VSCode',
                    content='Failed to setup: uninstalling service',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
    finally:
        await check_status()


async def restart() -> None:
    store.dispatch(VSCodeSetPendingAction())
    try:
        process = await asyncio.create_subprocess_exec(
            CODE_BINARY_PATH,
            'tunnel',
            '--accept-server-license-terms',
            'restart',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=3)
        if process.returncode is None:
            process.kill()
    except (subprocess.CalledProcessError, TimeoutError):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='VSCode',
                    content='Failed to restart process',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
    finally:
        await check_status()
