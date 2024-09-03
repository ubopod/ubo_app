# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
import re
import subprocess
from typing import TypedDict

from debouncer import DebounceOptions, debounce
from ubo_gui.constants import DANGER_COLOR

from ubo_app.logging import logger
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationExtraInformation,
    NotificationsAddAction,
)
from ubo_app.store.services.rpi_connect import (
    RPiConnectDoneDownloadingAction,
    RPiConnectSetPendingAction,
    RPiConnectSetStatusAction,
    RPiConnectStartDownloadingAction,
    RPiConnectStatus,
    RPiConnectUpdateServiceStateAction,
)
from ubo_app.utils.apt import is_package_installed
from ubo_app.utils.async_ import create_task
from ubo_app.utils.monitor_unit import is_unit_active
from ubo_app.utils.server import send_command


class ConnectServiceStatus(TypedDict):
    screen_sharing_sessions: int | None
    remote_shell_sessions: int | None


@debounce(
    wait=0.5,
    options=DebounceOptions(leading=True, trailing=False, time_window=0.5),
)
async def _check_status() -> None:
    await check_is_active()
    is_installed = await is_package_installed('rpi-connect')
    is_signed_in = None
    status_data: ConnectServiceStatus | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'rpi-connect',
            'status',
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=3)
        if process.returncode is None:
            process.kill()
        if process.stdout and process.returncode == 0:
            output = (await process.stdout.read()).decode()

            data = re.search(
                r"""Signed in: (yes|no)
(?:Screen sharing: (allowed|unavailable)(?: \((\d+) sessions active\))?
Remote shell: (allowed|unavailable)(?: \((\d+) sessions active\))?)?""",
                output,
            )

            if data:
                is_signed_in = data.group(1) == 'yes'
                status_data = {
                    'screen_sharing_sessions': int(data.group(3))
                    if data.group(2) == 'allowed'
                    else None,
                    'remote_shell_sessions': int(data.group(5))
                    if data.group(4) == 'allowed'
                    else None,
                }
    except (subprocess.CalledProcessError, TimeoutError):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='RPi-Connect',
                    content='Failed to get status: "status" subcommand',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
    logger.info(
        'Checked VSCode Tunnel Status',
        extra=status_data,
    )
    store.dispatch(
        RPiConnectSetStatusAction(
            is_installed=is_installed,
            is_signed_in=is_signed_in,
            status=None
            if status_data is None
            else RPiConnectStatus(
                screen_sharing_sessions=status_data['screen_sharing_sessions'],
                remote_shell_sessions=status_data['remote_shell_sessions'],
            ),
        ),
    )


def install_rpi_connect() -> None:
    store.dispatch(RPiConnectStartDownloadingAction())

    async def act() -> None:
        result = await send_command(
            'package',
            'install',
            'rpi-connect',
            has_output=True,
        )

        store.dispatch(RPiConnectDoneDownloadingAction())
        if result != 'installed':
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='RPi-Connect',
                        content='Failed to install',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
        await check_status()

    create_task(act())


def uninstall_rpi_connect() -> None:
    store.dispatch(RPiConnectSetPendingAction())

    async def act() -> None:
        result = await send_command(
            'package',
            'uninstall',
            'rpi-connect',
            has_output=True,
        )

        if result != 'uninstalled':
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='RPi-Connect',
                        content='Failed to uninstall',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
        await check_status()

    create_task(act())


def sign_out() -> None:
    async def act() -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'rpi-connect',
                'signout',
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await process.wait()
            await check_status()
        except subprocess.CalledProcessError:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='RPi-Connect',
                        content='Failed to logout',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )

    create_task(act())


@store.view(lambda state: state.lightdm.is_active)
def start_service(is_lightdm_active: bool) -> None:  # noqa: FBT001
    """Start the RPi Connect service."""

    async def act() -> None:
        if not is_lightdm_active:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='RPi-Connect',
                        content='LightDM is not running',
                        extra_information=NotificationExtraInformation(
                            text="""\
LightDM is not running so RPi-Connect will run without screen sharing and you can only \
use the remote shell feature. To enable screen sharing, start LightDM service in \
Settings → Desktop → LightDM menu, then come back here to stop and start RPi-Connect \
again.""",
                            piper_text="""\
LightDM is not running so RPi-Connect will run without screen sharing and you can only \
use the remote shell feature. To enable screen sharing, start LightDM service in \
LightDM item under Desktop menu under Settings menu, then come back here to stop and \
start RPi-Connect again.""",
                            picovoice_text="""\
LightDM is not running so RPi-Connect will run without screen sharing and you can only \
use the remote shell feature. To enable screen sharing, start LightDM service in \
LightDM item under Desktop menu under Settings menu, then come back here to stop and \
start RPi-Connect again.""",
                        ),
                        display_type=NotificationDisplayType.STICKY,
                        importance=Importance.LOW,
                    ),
                ),
            )
        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'systemctl',
            '--user',
            'start',
            'rpi-connect',
        )
        await process.wait()
        await check_status()

    create_task(act())


def stop_service() -> None:
    """Stop the RPi Connect service."""

    async def act() -> None:
        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'systemctl',
            '--user',
            'stop',
            'rpi-connect',
        )
        await process.wait()
        await check_status()

    create_task(act())


async def check_is_active() -> None:
    """Check if the SSH service is active."""
    if await is_unit_active('rpi-connect', is_user_service=True):
        store.dispatch(RPiConnectUpdateServiceStateAction(is_active=True))
    else:
        store.dispatch(RPiConnectUpdateServiceStateAction(is_active=False))


async def check_status() -> None:
    await _check_status()
