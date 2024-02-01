"""Update manager module."""
from __future__ import annotations

import asyncio
import importlib.metadata
from pathlib import Path

import aiohttp
from kivy import shutil
from ubo_gui.constants import DANGER_COLOR, SUCCESS_COLOR
from ubo_gui.menu.types import ActionItem, Item

from ubo_app.constants import INSTALLATION_PATH
from ubo_app.logging import logger
from ubo_app.store import autorun, dispatch
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

CURRENT_VERSION = importlib.metadata.version('ubo_app')


async def check_version() -> None:
    """Check for updates."""
    logger.info('Checking for updates...')

    # Check PyPI server for the latest version
    import requests

    try:
        async with aiohttp.ClientSession() as session, session.get(
            'https://pypi.org/pypi/ubo-app/json',
            timeout=5,
        ) as response:
            if response.status != requests.codes.ok:
                logger.error('Failed to check for updates')
                return
            data = await response.json()
            latest_version = data['info']['version']

            dispatch(
                with_state=lambda state: UpdateManagerSetVersionsAction(
                    flash_notification=state is None
                    or state.main.path[:3] != ABOUT_MENU_PATH,
                    current_version=CURRENT_VERSION,
                    latest_version=latest_version,
                ),
            )
    except Exception as exception:  # noqa: BLE001
        logger.error('Failed to check for updates', exc_info=exception)
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
        )
        await process.wait()
    except Exception as exception:  # noqa: BLE001
        logger.error('Failed to update', exc_info=exception)
        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Failed to update',
                    content='Failed to update',
                    display_type=NotificationDisplayType.FLASH,
                    color=DANGER_COLOR,
                    icon='security_update_warning',
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
            ActionItem(
                label='Checking for updates...',
                action=lambda: None,
                icon='update',
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
                icon='security_update_warning',
                background_color=DANGER_COLOR,
            ),
        ]
    if state.update_status is UpdateStatus.UP_TO_DATE:
        return [
            ActionItem(
                label='Already up to date!',
                action=lambda: None,
                icon='security_update_good',
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
                icon='system_update',
            ),
        ]
    if state.update_status is UpdateStatus.UPDATING:
        return [
            ActionItem(
                label='Updating...',
                action=lambda: None,
                icon='update',
                background_color='#00000000',
            ),
        ]
    return []
