# ruff: noqa: D100, D103
from __future__ import annotations

import asyncio
import json
import subprocess

from debouncer import DebounceOptions, debounce

from ubo_app.colors import DANGER_COLOR
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.tailscale import (
    TailscaleDoneDownloadingAction,
    TailscaleSetPendingAction,
    TailscaleSetStatusAction,
    TailscaleStartDownloadingAction,
)
from ubo_app.utils.apt import is_package_installed
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.server import send_command


def _notify_failure(content: str) -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='Tailscale',
                content=content,
                display_type=NotificationDisplayType.STICKY,
                color=DANGER_COLOR,
                icon='󰜺',
                chime=Chime.FAILURE,
            ),
        ),
    )


@debounce(
    wait=0.5,
    options=DebounceOptions(leading=True, trailing=False, time_window=0.5),
)
async def _check_status() -> None:
    is_installed = await is_package_installed('tailscale')
    backend_state: str | None = None
    if is_installed:
        try:
            process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'tailscale',
                'status',
                '--json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=5)
            if process.returncode is None:
                process.kill()
            if process.stdout and process.returncode == 0:
                output = (await process.stdout.read()).decode()
                if output.strip():
                    backend_state = json.loads(output).get('BackendState')
        except (subprocess.CalledProcessError, TimeoutError, json.JSONDecodeError):
            _notify_failure('Failed to get status')
            report_service_error()
    logger.info(
        'Checked Tailscale Status',
        extra={'is_installed': is_installed, 'backend_state': backend_state},
    )
    store.dispatch(
        TailscaleSetStatusAction(
            is_installed=is_installed,
            backend_state=backend_state,
        ),
    )


async def check_status() -> None:
    await _check_status()


def install_tailscale() -> None:
    store.dispatch(TailscaleStartDownloadingAction())

    async def act() -> None:
        result = await send_command('tailscale', 'install', has_output=True)

        store.dispatch(TailscaleDoneDownloadingAction())
        if result != 'installed':
            _notify_failure('Failed to install')
        await check_status()

    create_task(act())


def uninstall_tailscale() -> None:
    store.dispatch(TailscaleSetPendingAction())

    async def act() -> None:
        result = await send_command('tailscale', 'uninstall', has_output=True)

        if result != 'uninstalled':
            _notify_failure('Failed to uninstall')
        await check_status()

    create_task(act())


def _run_tailscale(*args: str, failure_message: str) -> None:
    async def act() -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'tailscale',
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            await check_status()
        except subprocess.CalledProcessError:
            _notify_failure(failure_message)
            raise

    create_task(act())


def connect() -> None:
    """Connect to Tailscale (already authenticated)."""
    _run_tailscale('up', failure_message='Failed to connect')


def disconnect() -> None:
    """Disconnect from Tailscale."""
    _run_tailscale('down', failure_message='Failed to disconnect')


def sign_out() -> None:
    """Log out of Tailscale."""
    _run_tailscale('logout', failure_message='Failed to log out')
