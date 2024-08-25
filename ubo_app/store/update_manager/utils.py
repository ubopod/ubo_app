"""Update manager module."""

from __future__ import annotations

import asyncio
import importlib.metadata
import shutil
import subprocess
import time
from pathlib import Path
from typing import TypedDict

import aiohttp
import requests
from ubo_gui.constants import DANGER_COLOR, INFO_COLOR, SUCCESS_COLOR
from ubo_gui.menu.types import ActionItem, Item

from ubo_app.constants import (
    INSTALLATION_PATH,
    INSTALLER_URL,
    UPDATE_ASSETS_PATH,
    UPDATE_LOCK_PATH,
)
from ubo_app.logging import logger
from ubo_app.store.core import RebootEvent
from ubo_app.store.main import autorun, dispatch
from ubo_app.store.services.notifications import (
    Chime,
    Importance,
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationExtraInformation,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.store.update_manager import (
    UPDATE_MANAGER_NOTIFICATION_ID,
    UPDATE_MANAGER_SECOND_PHASE_NOTIFICATION_ID,
    UpdateManagerSetStatusAction,
    UpdateManagerSetVersionsAction,
    UpdateManagerState,
    UpdateStatus,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.eeprom import read_serial_number

CURRENT_VERSION = importlib.metadata.version('ubo_app')
if IS_RPI:
    try:
        BASE_IMAGE = Path('/etc/ubo_base_image').read_text()
    except FileNotFoundError:
        BASE_IMAGE = '[unknown]'
else:
    BASE_IMAGE = '[unknown]'
BASE_IMAGE_VARIANT = (
    BASE_IMAGE == '[unknown]'
    and '[unknown]'
    or BASE_IMAGE.endswith('-lite')
    and 'lite'
    or BASE_IMAGE.endswith('-full')
    and 'full'
    or 'desktop'
)


async def check_version() -> None:
    """Check for updates."""
    logger.info('Checking for updates...')

    # Check PyPI server for the latest version
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                'https://pypi.org/pypi/ubo-app/json',
                timeout=aiohttp.ClientTimeout(total=5),
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
                    or state.main.path[:2] != ['main', 'about'],
                    current_version=CURRENT_VERSION,
                    base_image_variant=BASE_IMAGE_VARIANT,
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

    extra_information = NotificationExtraInformation(
        text="""\
The download progress is shown in the radial progress bar at the top left corner of \
the screen.
Once the download is complete, the system will reboot to apply the update.
Then another reboot will be done to complete the update process.""",
    )

    async def download_files() -> None:
        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=UPDATE_MANAGER_NOTIFICATION_ID,
                    title='Update in progress',
                    content='Downloading the latest version of the install script...',
                    extra_information=extra_information,
                    display_type=NotificationDisplayType.STICKY,
                    color=INFO_COLOR,
                    icon='󰇚',
                    blink=False,
                    progress=0,
                    dismissable=False,
                ),
            ),
        )

        shutil.rmtree(UPDATE_ASSETS_PATH, ignore_errors=True)
        UPDATE_ASSETS_PATH.mkdir(parents=True, exist_ok=True)

        packages_count_path = f'{INSTALLATION_PATH}/.packages-count'
        try:
            packages_count = int(Path(packages_count_path).read_text(encoding='utf-8'))
        except FileNotFoundError:
            packages_count = 55
        packages_count *= 2
        packages_count += 1
        counter = 0

        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'curl',
            '-Lk',
            INSTALLER_URL,
            '--output',
            UPDATE_ASSETS_PATH / 'install.sh',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await process.wait()
        (UPDATE_ASSETS_PATH / 'install.sh').chmod(0o755)

        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=UPDATE_MANAGER_NOTIFICATION_ID,
                    title='Update in progress',
                    content='Fetching the latest version of Ubo app...',
                    extra_information=extra_information,
                    display_type=NotificationDisplayType.BACKGROUND,
                    color=INFO_COLOR,
                    icon='󰇚',
                    blink=False,
                    progress=1 / packages_count,
                    dismissable=False,
                ),
            ),
        )

        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'pip',
            'download',
            '--dest',
            UPDATE_ASSETS_PATH,
            'setuptools',
            'wheel',
            'ubo-app[default]',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdout is None:
            logger.info('Failed to update (pip has no stdout)')
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
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

        while True:
            line = (await process.stdout.readline()).decode()
            if not line:
                break
            if line.startswith(('Collecting', 'Requirement already satisfied')):
                counter += 1
                dispatch(
                    NotificationsAddAction(
                        notification=Notification(
                            id=UPDATE_MANAGER_NOTIFICATION_ID,
                            title='Update in progress',
                            content=f'Downloading {line.partition(" ")[2].strip()}',
                            extra_information=extra_information,
                            display_type=NotificationDisplayType.BACKGROUND,
                            color=INFO_COLOR,
                            icon='󰇚',
                            blink=False,
                            progress=min((counter + 1) / packages_count, 1),
                            dismissable=False,
                        ),
                    ),
                )
        await process.wait()

        if process.returncode != 0:
            msg = 'Failed to download packages'
            raise RuntimeError(msg)

        # Update the packages count estimate for the next update
        Path(packages_count_path).write_text(str(counter), encoding='utf-8')

        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=UPDATE_MANAGER_NOTIFICATION_ID,
                    title='Update in progress',
                    content="""\
All packages downloaded successfully.
Press 󰜉 button to reboot now or dismiss this notification to reboot later.""",
                    extra_information=NotificationExtraInformation(
                        text="""\
After the reboot, the system will apply the update.
This part may take around 20 minutes to complete.
Then another reboot will be done to complete the update process.""",
                    ),
                    actions=[
                        NotificationActionItem(
                            icon='󰜉',
                            action=lambda: dispatch(RebootEvent()),
                        ),
                    ],
                    display_type=NotificationDisplayType.STICKY,
                    color=INFO_COLOR,
                    icon='󰇚',
                    progress=1,
                    dismissable=False,
                ),
            ),
        )

        UPDATE_LOCK_PATH.touch()

    try:
        await download_files()
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
            ActionItem(
                label='Already up to date!',
                icon='󰄬',
                action=lambda: dispatch(
                    UpdateManagerSetStatusAction(status=UpdateStatus.CHECKING),
                ),
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


class _UpdateManagerServiceState(TypedDict):
    is_running: bool
    is_presented: bool
    progress: int


@autorun(
    lambda state: _UpdateManagerServiceState(
        is_running=state.update_manager.is_update_service_active,
        is_presented=any(
            notification.id == UPDATE_MANAGER_NOTIFICATION_ID
            for notification in state.notifications.notifications
        ),
        progress=int(time.time() / 2),
    ),
)
def _(state: _UpdateManagerServiceState) -> None:
    if state['is_running']:
        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=UPDATE_MANAGER_SECOND_PHASE_NOTIFICATION_ID,
                    title='Update in progress',
                    content="""\
Please keep the device powered on.
This may take around 20 minutes to complete.""",
                    importance=Importance.LOW,
                    icon='󰚰',
                    display_type=NotificationDisplayType.BACKGROUND
                    if state['is_presented']
                    else NotificationDisplayType.STICKY,
                    dismissable=False,
                    dismiss_on_close=False,
                    color=INFO_COLOR,
                    progress=(state['progress'] % 4 + 1) / 4,
                    blink=not state['is_presented'],
                ),
            ),
        )
    else:
        dispatch(
            NotificationsClearByIdAction(
                id=UPDATE_MANAGER_SECOND_PHASE_NOTIFICATION_ID,
            ),
        )
