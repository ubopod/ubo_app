"""Update manager module."""

from __future__ import annotations

import asyncio
import importlib.metadata
import shutil
import subprocess
from pathlib import Path

import aiohttp
import requests
from ubo_gui.constants import DANGER_COLOR, INFO_COLOR, SUCCESS_COLOR
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
from ubo_app.utils.eeprom import read_serial_number

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

            serial_number = read_serial_number()
            dispatch(
                with_state=lambda state: UpdateManagerSetVersionsAction(
                    flash_notification=state is None
                    # TODO(Sassan): We need a better approach for  # noqa: FIX002, TD003
                    # serializing and checking paths of menus
                    or state.main.path[1:3] != ['Main', 'About'],
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
    dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='ubo:update_manager',
                title='Updating...',
                content='Fetching the latest version of Ubo app...',
                display_type=NotificationDisplayType.BACKGROUND,
                color=INFO_COLOR,
                icon='󰇚',
                blink=False,
                progress=0,
            ),
        ),
    )

    async def download_files() -> None:
        target_path = Path(f'{INSTALLATION_PATH}/_update/')
        shutil.rmtree(target_path, ignore_errors=True)
        target_path.mkdir(parents=True, exist_ok=True)

        packages_count_path = f'{INSTALLATION_PATH}/.packages-count'

        try:
            packages_count = int(Path(packages_count_path).read_text(encoding='utf-8'))
        except FileNotFoundError:
            packages_count = 55

        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'pip',
            'download',
            '--dest',
            target_path,
            'ubo-app[default]',
            'setuptools',
            'wheel',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdout is None:
            logger.exception('Failed to update (pip has no stdout)')
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id='ubo:update_manager',
                        title='Failed to update',
                        content='Failed to download packages',
                        display_type=NotificationDisplayType.FLASH,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
                UpdateManagerSetStatusAction(status=UpdateStatus.CHECKING),
            )
            return
        counter = 0
        while True:
            line = (await process.stdout.readline()).decode()
            if not line:
                break
            if line.startswith('Collecting'):
                counter += 1
                dispatch(
                    NotificationsAddAction(
                        notification=Notification(
                            id='ubo:update_manager',
                            title='Updating...',
                            content=f'Downloading {line.partition(" ")[2].strip()}',
                            display_type=NotificationDisplayType.BACKGROUND,
                            color=INFO_COLOR,
                            icon='󰇚',
                            blink=False,
                            progress=min(counter / (packages_count * 2), 1),
                        ),
                    ),
                )
        await process.wait()

        # Update the packages count estimate for the next update
        Path(packages_count_path).write_text(str(counter), encoding='utf-8')

        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='ubo:update_manager',
                    title='Updating...',
                    content='All packages downloaded successfully, rebooting...',
                    display_type=NotificationDisplayType.STICKY,
                    color=INFO_COLOR,
                    icon='󰇚',
                    progress=1,
                ),
            ),
        )
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
