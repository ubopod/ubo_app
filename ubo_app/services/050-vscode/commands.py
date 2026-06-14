# ruff: noqa: D100, D101, D103
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
from typing import Literal, TypedDict

from constants_ import CODE_BINARY_PATH
from debouncer import DebounceOptions, debounce

from ubo_app.colors import DANGER_COLOR
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.store.services.vscode import (
    VSCodeSetPendingAction,
    VSCodeSetStatusAction,
    VSCodeStatus,
)

# Serializes binary (re)downloads against status probes: `check_status` exec's
# the `code` binary, and while a download is rewriting it on disk exec'ing
# raises `OSError(26, 'Text file busy')` (ETXTBSY).
download_lock = asyncio.Lock()

# `_monitor_status` polls `check_status` every second; a single slow/timed-out
# `code tunnel` subcommand is normal jitter, not a fault. Count consecutive
# failures (module-level list, not a global) and only surface the sticky error
# + failure chime once the CLI has been unreachable for several polls in a row,
# clearing it again as soon as a poll succeeds. This stops a transient timeout
# from flashing an error and replaying the chime on screen.
_consecutive_failures = [0]
_FAILURE_NOTIFICATION_THRESHOLD = 3


def _note_status_failure(notification_id: str, content: str) -> None:
    """Record a failed status poll; notify only when it becomes persistent."""
    _consecutive_failures[0] += 1
    if _consecutive_failures[0] == _FAILURE_NOTIFICATION_THRESHOLD:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=notification_id,
                    title='VSCode',
                    content=content,
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )


def _note_status_success() -> None:
    """Reset the failure counter and clear any sticky error after recovery."""
    if _consecutive_failures[0] >= _FAILURE_NOTIFICATION_THRESHOLD:
        store.dispatch(NotificationsClearByIdAction(id='vscode:error:user'))
        store.dispatch(NotificationsClearByIdAction(id='vscode:error:status'))
    _consecutive_failures[0] = 0


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
    # While a (re)download is in progress the `code` binary on disk is being
    # written/replaced by `tar`/`code version use`. Exec'ing it concurrently
    # raises `OSError(26, 'Text file busy')` (ETXTBSY), and the
    # `_monitor_status` loop polls this every second. `download_code` holds
    # `download_lock` for the duration of the download, so skip the probe
    # while it is held — `download_code` calls `check_status` again from its
    # `finally`, once the lock is released and the binary is closed.
    if download_lock.locked():
        return
    is_binary_installed = CODE_BINARY_PATH.exists()
    status_data: TunnelServiceStatus | None = None
    is_logged_in = False
    if is_binary_installed:
        # `user show` first: fast, deterministic, and the only safe gate before
        # calling `tunnel status` — `code tunnel status` busy-loops forever
        # waiting on a tunnel daemon socket in /tmp when no tunnel is running.
        try:
            process = await asyncio.create_subprocess_exec(
                CODE_BINARY_PATH.as_posix(),
                'tunnel',
                '--accept-server-license-terms',
                'user',
                'show',
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(process.communicate(), timeout=3)
            except TimeoutError:
                process.kill()
                raise
            is_logged_in = process.returncode == 0
        except (subprocess.CalledProcessError, TimeoutError):
            _note_status_failure(
                'vscode:error:user',
                'Failed to get status: "user show" subcommand',
            )
            return

        if is_logged_in:
            try:
                process = await asyncio.create_subprocess_exec(
                    CODE_BINARY_PATH.as_posix(),
                    'tunnel',
                    '--accept-server-license-terms',
                    'status',
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    stdout_bytes, _ = await asyncio.wait_for(
                        process.communicate(),
                        timeout=3,
                    )
                except TimeoutError:
                    process.kill()
                    raise
                if process.returncode == 0 and stdout_bytes:
                    status_data = json.loads(stdout_bytes)
            except (subprocess.CalledProcessError, TimeoutError):
                _note_status_failure(
                    'vscode:error:status',
                    'Failed to get status: "status" subcommand',
                )
                return
    _note_status_success()
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
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=3)
        if process.returncode is None:
            process.kill()
    except (subprocess.CalledProcessError, TimeoutError):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='vscode:error:rename',
                    title='VSCode',
                    content='Failed to setup: renaming the tunnel',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
        raise
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
                    id='vscode:error:install',
                    title='VSCode',
                    content='Failed to setup: installing service',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
        raise
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
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=3)
        if process.returncode is None:
            process.kill()
    except (subprocess.CalledProcessError, TimeoutError):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='vscode:error:uninstall',
                    title='VSCode',
                    content='Failed to setup: uninstalling service',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
        raise
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
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=3)
        if process.returncode is None:
            process.kill()
    except (subprocess.CalledProcessError, TimeoutError):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='vscode:error:restart',
                    title='VSCode',
                    content='Failed to restart process',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
        raise
    finally:
        await check_status()
