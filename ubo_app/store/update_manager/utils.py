"""Update manager module."""

from __future__ import annotations

import asyncio
import importlib.metadata
import shutil
import tarfile
from dataclasses import replace
from pathlib import Path

import aiohttp
import requests
from kivy.clock import Clock
from redux import FinishEvent
from ubo_gui.menu.menu_widget import math
from ubo_gui.menu.types import HeadlessMenu, Item, SubMenuItem

from ubo_app.colors import DANGER_COLOR, INFO_COLOR, SUCCESS_COLOR
from ubo_app.constants import (
    INSTALLATION_PATH,
    PACKAGE_NAME,
    UPDATE_ASSETS_PATH,
    UPDATE_LOCK_PATH,
)
from ubo_app.logger import logger
from ubo_app.store.core.types import RebootAction
from ubo_app.store.dispatch_action import DispatchItem
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Importance,
    Notification,
    NotificationDispatchItem,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.update_manager.types import (
    UPDATE_MANAGER_NOTIFICATION_ID,
    UPDATE_MANAGER_SECOND_PHASE_NOTIFICATION_ID,
    UpdateManagerReportFailedCheckAction,
    UpdateManagerRequestCheckAction,
    UpdateManagerRequestUpdateAction,
    UpdateManagerSetVersionsAction,
    UpdateManagerState,
    UpdateManagerUpdateEvent,
    UpdateStatus,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.download import download_file

CURRENT_VERSION = importlib.metadata.version(PACKAGE_NAME)
if IS_RPI:
    try:
        BASE_IMAGE = Path('/etc/ubo_base_image').read_text()
    except FileNotFoundError:
        BASE_IMAGE = '[unknown]'
else:
    BASE_IMAGE = '[unknown]'
BASE_IMAGE_VARIANT = (
    (BASE_IMAGE == '[unknown]' and '[unknown]')
    or (BASE_IMAGE.endswith('-lite') and 'lite')
    or (BASE_IMAGE.endswith('-full') and 'full')
    or 'desktop'
)


@store.with_state(lambda state: state.settings.beta_versions)
async def check_version(beta_versions: bool) -> None:  # noqa: FBT001
    """Check for updates."""
    logger.info('Checking for updates...', extra={'beta_versions': beta_versions})

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
            if beta_versions:
                recent_versions = [
                    version
                    for version, data in data['releases'].items()
                    if not data[0]['yanked']
                ]
                recent_versions = sorted(
                    recent_versions,
                    key=lambda x: data['releases'][x][0]['upload_time'],
                    reverse=True,
                )[:12]
            else:
                recent_versions = [
                    version
                    for version, data in data['releases'].items()
                    if '.dev' not in version and not data[0]['yanked']
                ]
                recent_versions = sorted(
                    recent_versions,
                    key=lambda x: data['releases'][x][0]['upload_time'],
                    reverse=True,
                )[:3]

            if beta_versions:
                latest_version = recent_versions[0]
            else:
                latest_version = data['info']['version']

            store.dispatch(
                with_state=lambda state: UpdateManagerSetVersionsAction(
                    flash_notification=state is None
                    or state.main.path[:2] != ['main', 'about'],
                    current_version=CURRENT_VERSION,
                    base_image_variant=BASE_IMAGE_VARIANT,
                    latest_version=latest_version,
                    recent_versions=recent_versions,
                ),
            )
    except Exception:
        logger.exception('Failed to check for updates')
        store.dispatch(UpdateManagerReportFailedCheckAction())
        return


async def _download_files(target_version: str | None) -> None:
    extra_information = ReadableInformation(
        text="""\
The download progress is shown in the radial progress bar at the top left corner of \
the screen.
Once the download is complete, the system will reboot to apply the update.
Then another reboot will be done to complete the update process.""",
    )

    install_script_notification = Notification(
        id=UPDATE_MANAGER_NOTIFICATION_ID,
        title='Update in progress',
        content='Downloading the latest version of the install script...',
        extra_information=extra_information,
        display_type=NotificationDisplayType.STICKY,
        color=INFO_COLOR,
        icon='󰇚',
        blink=False,
        progress=0,
        show_dismiss_action=False,
    )

    store.dispatch(NotificationsAddAction(notification=install_script_notification))

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

    async for report in download_file(
        url=f'https://files.pythonhosted.org/packages/source/u/ubo_app/ubo_app-{target_version}.tar.gz',
        path=UPDATE_ASSETS_PATH / 'package.tar.gz',
    ):
        store.dispatch(
            NotificationsAddAction(
                notification=replace(
                    install_script_notification,
                    progress=report[0] / report[1] if report[1] else 0,
                ),
            ),
        )

    # Extract solely the install.sh file using python's tarfile module
    with tarfile.open(
        UPDATE_ASSETS_PATH / 'package.tar.gz',
        'r:gz',
    ) as tar:
        members = [
            m for m in tar.getmembers() if m.name.endswith('ubo_app/system/install.sh')
        ]
        if not members:
            msg = 'Failed to extract install.sh'
            raise RuntimeError(msg)
        tar.extract(
            members[0],
            path=UPDATE_ASSETS_PATH,
            filter=lambda tar_info, _: tar_info.replace(name='install.sh'),
        )

    (UPDATE_ASSETS_PATH / 'install.sh').chmod(0o755)

    store.dispatch(
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
                show_dismiss_action=False,
            ),
        ),
    )

    process = await asyncio.create_subprocess_exec(
        (UPDATE_ASSETS_PATH / 'install.sh'),
        '--update-preparation',
        'setuptools',
        'wheel',
        'ubo-app',
        *(
            [
                '--target-version',
                target_version,
            ]
            if target_version
            else []
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if process.stdout is None:
        logger.info('Failed to update (pip has no stdout)')
        store.dispatch(
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
            UpdateManagerRequestCheckAction(),
        )
        return

    while True:
        line = (await process.stdout.readline()).decode()
        if not line:
            break
        if line.startswith(('Collecting', 'Requirement already satisfied')):
            counter += 1
            store.dispatch(
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
                        show_dismiss_action=False,
                    ),
                ),
            )
    await process.wait()

    if process.returncode != 0:
        msg = 'Failed to download packages'
        raise RuntimeError(msg)

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=UPDATE_MANAGER_NOTIFICATION_ID,
                title='Update in progress',
                content="""\
All packages downloaded successfully.
Press 󰜉 button to reboot now or dismiss this notification to reboot later.""",
                extra_information=ReadableInformation(
                    text="""\
After the reboot, the system will apply the update.
This part may take around 20 minutes to complete.
Then another reboot will be done to complete the update process.""",
                ),
                actions=[
                    NotificationDispatchItem(
                        icon='󰜉',
                        store_action=RebootAction(),
                    ),
                ],
                display_type=NotificationDisplayType.STICKY,
                color=INFO_COLOR,
                icon='󰇚',
                progress=1,
                show_dismiss_action=False,
            ),
        ),
    )

    UPDATE_LOCK_PATH.touch()


async def update(event_request_event: UpdateManagerUpdateEvent) -> None:
    """Update the Ubo app."""
    logger.info('Updating Ubo app...')
    target_version = event_request_event.version

    try:
        await _download_files(target_version)
    except Exception:
        logger.exception('Failed to update')
        store.dispatch(
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
            UpdateManagerRequestCheckAction(),
        )
        return


@store.autorun(lambda state: state.update_manager)
def about_menu_items(state: UpdateManagerState) -> list[Item]:
    """Get the update menu items."""
    items: list[Item] = []

    recent_versions_item = SubMenuItem(
        key='recent_versions',
        label='Recent versions',
        icon='󰜉',
        sub_menu=HeadlessMenu(
            title='󰜉Recent versions',
            items=[
                DispatchItem(
                    label=version,
                    store_action=NotificationsAddAction(
                        notification=Notification(
                            title=f'Install {version} now?',
                            content='Press 󰜉 button to startn installation of version '
                            f'"{version}"',
                            icon='󰜉',
                            extra_information=ReadableInformation(
                                text="""Do you want to replace the current installed \
version of ubo-app with the selected version?""",
                            ),
                            color=INFO_COLOR,
                            dismiss_on_close=True,
                            display_type=NotificationDisplayType.STICKY,
                            show_dismiss_action=True,
                            actions=[
                                NotificationDispatchItem(
                                    icon='󰜉',
                                    store_action=UpdateManagerRequestUpdateAction(
                                        version=version,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    icon='󰜉',
                )
                for version in state.recent_versions
            ],
        ),
    )

    if state.update_status is UpdateStatus.CHECKING:
        items = [
            Item(
                label='Checking for updates...',
                icon='󰬬',
                background_color='#00000000',
            ),
        ]
    if state.update_status is UpdateStatus.FAILED_TO_CHECK:
        items = [
            DispatchItem(
                label='Failed to check for updates',
                store_action=UpdateManagerRequestCheckAction(),
                icon='󰜺',
                background_color=DANGER_COLOR,
            ),
        ]
    if state.update_status is UpdateStatus.UP_TO_DATE:
        items = [
            DispatchItem(
                label='Already up to date!',
                icon='󰄬',
                store_action=UpdateManagerRequestCheckAction(),
                background_color=SUCCESS_COLOR,
                color='#000000',
            ),
            recent_versions_item,
        ]
    if state.update_status is UpdateStatus.OUTDATED:
        items = [
            DispatchItem(
                label=f'Update to v{state.latest_version}',
                store_action=UpdateManagerRequestUpdateAction(),
                icon='󰬬',
            ),
            recent_versions_item,
        ]
    if state.update_status is UpdateStatus.UPDATING:
        items = [
            Item(
                label='Updating...',
                icon='󰇚',
                background_color='#00000000',
            ),
        ]

    return items


@store.view(
    lambda state: any(
        notification.id == UPDATE_MANAGER_SECOND_PHASE_NOTIFICATION_ID
        for notification in state.notifications.notifications
    ),
)
def dispatch_notification(is_presented: bool, _: float = 0) -> None:  # noqa: FBT001
    """Dispatch the notification."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=UPDATE_MANAGER_SECOND_PHASE_NOTIFICATION_ID,
                title='Update in progress',
                content="""\
Please keep the device powered on.
This may take around 20 minutes to complete.""",
                importance=Importance.LOW,
                icon='',
                display_type=NotificationDisplayType.BACKGROUND
                if is_presented
                else NotificationDisplayType.STICKY,
                show_dismiss_action=False,
                dismiss_on_close=False,
                color=INFO_COLOR,
                progress=math.nan,
                blink=not is_presented,
            ),
        ),
    )


def sync_with_update_service() -> None:
    """Run an autorun to show a notification when the update service is running."""
    update_clock_event = Clock.create_trigger(
        dispatch_notification,
        timeout=2,
        interval=True,
    )

    store.subscribe_event(FinishEvent, update_clock_event.cancel)

    @store.autorun(
        lambda state: state.update_manager.is_update_service_active,
    )
    async def _(is_running: bool) -> None:  # noqa: FBT001
        if is_running:
            dispatch_notification()
            update_clock_event()
        else:
            update_clock_event.cancel()
            await asyncio.sleep(0.2)
            store.dispatch(
                NotificationsClearByIdAction(
                    id=UPDATE_MANAGER_SECOND_PHASE_NOTIFICATION_ID,
                ),
            )
