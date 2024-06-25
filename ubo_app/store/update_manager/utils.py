"""Update manager module."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import shutil
import subprocess
from pathlib import Path

import aiohttp
import requests
from ubo_gui.constants import DANGER_COLOR, SUCCESS_COLOR
from ubo_gui.menu.types import ActionItem, Item

from ubo_app.constants import INSTALLATION_PATH
from ubo_app.logging import logger
from ubo_app.store.main import autorun, dispatch
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.update_manager import (
    UpdateManagerSetStatusAction,
    UpdateManagerSetVersionsAction,
    UpdateManagerState,
    UpdateStatus,
)
from ubo_app.store.update_manager.reducer import ABOUT_MENU_PATH
from ubo_app.utils import IS_RPI

CURRENT_VERSION = importlib.metadata.version('ubo_app')


async def check_version() -> None:
    """Check for updates."""
    logger.info('Checking for updates...')

    # Check PyPI server for the latest version
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                'https://pypi.org/pypi/ubo-app/json',
                timeout=5,
            ) as response,
        ):
            if response.status != requests.codes.ok:
                logger.error('Failed to check for updates')
                return
            data = await response.json()
            latest_version = data['info']['version']

            serial_number = '<not-available>'
            if IS_RPI:
                try:
                    eeprom_json_data = Path(
                        '/proc/device-tree/hat/custom_0',
                    ).read_text()
                    eeprom_data = json.loads(eeprom_json_data)
                    serial_number = eeprom_data['serial_number']
                except Exception:
                    logger.exception('Failed to read serial number')

                from sentry_sdk import set_user

                set_user({'id': serial_number})
            dispatch(
                with_state=lambda state: UpdateManagerSetVersionsAction(
                    flash_notification=state is None
                    or state.main.path[:3] != ABOUT_MENU_PATH,
                    current_version=CURRENT_VERSION,
                    latest_version=latest_version,
                    serial_number=serial_number,
                ),
            )
    except Exception:
        logger.exception('Failed to check for updates')
        dispatch(UpdateManagerSetStatusAction(status=UpdateStatus.FAILED_TO_CHECK))
        return


async def update() -> None:
    """Update the Ubo app."""
    logger.info('Updating Ubo app...')

    async def download_files() -> None:
        target_path = Path(f'{INSTALLATION_PATH}/_update/')
        shutil.rmtree(target_path, ignore_errors=True)
        target_path.mkdir(parents=True, exist_ok=True)

        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'pip',
            'download',
            '--dest',
            target_path,
            'ubo-app[default]',
            'setuptools',
            'wheel',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await process.wait()
        if process.returncode != 0:
            msg = 'Failed to download packages'
            raise RuntimeError(msg)

        target_path.joinpath('update_is_ready').touch()

    try:
        await download_files()

        await asyncio.sleep(2)

        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'systemctl',
            'reboot',
            '-i',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await process.wait()
    except Exception:
        logger.exception('Failed to update')
        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Failed to update',
                    content='Failed to update',
                    display_type=NotificationDisplayType.FLASH,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
            UpdateManagerSetStatusAction(status=UpdateStatus.CHECKING),
        )
        return


@autorun(lambda state: state.update_manager)
def about_menu_items(state: UpdateManagerState) -> list[Item]:
    """Get the update menu items."""
    if state.update_status is UpdateStatus.CHECKING:
        return [
            Item(
                label='Checking for updates...',
                icon='󰬬',
                background_color='#00000000',
            ),
        ]
    if state.update_status is UpdateStatus.FAILED_TO_CHECK:
        return [
            ActionItem(
                label='Failed to check for updates',
                action=lambda: dispatch(
                    UpdateManagerSetStatusAction(status=UpdateStatus.CHECKING),
                ),
                icon='󰜺',
                background_color=DANGER_COLOR,
            ),
        ]
    if state.update_status is UpdateStatus.UP_TO_DATE:
        return [
            Item(
                label='Already up to date!',
                icon='󰄬',
                background_color=SUCCESS_COLOR,
                color='#000000',
            ),
        ]
    if state.update_status is UpdateStatus.OUTDATED:
        return [
            ActionItem(
                label=f'Update to v{state.latest_version}',
                action=lambda: dispatch(
                    UpdateManagerSetStatusAction(status=UpdateStatus.UPDATING),
                ),
                icon='󰬬',
            ),
        ]
    if state.update_status is UpdateStatus.UPDATING:
        return [
            Item(
                label='Updating...',
                icon='󰇚',
                background_color='#00000000',
            ),
        ]
    return []
