"""Update manager module."""

from __future__ import annotations

import asyncio
import functools
import importlib.metadata
import shutil
import tarfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import requests
from debouncer import DebounceOptions, debounce
from redux import FinishAction
from ubo_gui.menu.types import HeadedMenu, HeadlessMenu, Item, SubMenuItem

from ubo_app.colors import DANGER_COLOR, INFO_COLOR, SUCCESS_COLOR
from ubo_app.constants import (
    INSTALLATION_PATH,
    PACKAGE_NAME,
    UPDATE_ASSETS_PATH,
)
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationActionItem,
    NotificationDispatchItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.store.update_manager.installed_versions import get_installed_versions
from ubo_app.store.update_manager.types import (
    UPDATE_MANAGER_NOTIFICATION_ID,
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
from ubo_app.utils.gui import SELECTED_ITEM_PARAMETERS, UNSELECTED_ITEM_PARAMETERS
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Callable

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
@debounce(6, options=DebounceOptions(leading=True, trailing=True, time_window=6))
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


UPDATE_PROGRESS_NOTIFICATION = Notification(
    id=UPDATE_MANAGER_NOTIFICATION_ID,
    title='Update in progress',
    content='Downloading the latest version of the install script...',
    extra_information=ReadableInformation(
        text="""\
The download progress is shown in the radial progress bar at the top left corner of \
the screen.
Once the download is complete, ubo app will quit and the new version will run.""",
    ),
    display_type=NotificationDisplayType.STICKY,
    color=INFO_COLOR,
    icon='󰇚',
    blink=False,
    progress=0,
    show_dismiss_action=False,
)


async def _update(target_version: str | None) -> None:
    store.dispatch(NotificationsAddAction(notification=UPDATE_PROGRESS_NOTIFICATION))

    shutil.rmtree(UPDATE_ASSETS_PATH, ignore_errors=True)
    UPDATE_ASSETS_PATH.mkdir(parents=True, exist_ok=True)

    packages_count_path = f'{INSTALLATION_PATH}/.packages-count'
    try:
        packages_count = int(Path(packages_count_path).read_text(encoding='utf-8'))
        _ = 1 / packages_count
    except (FileNotFoundError, ValueError, ZeroDivisionError):
        packages_count = 112
    counter = 0

    async for report in download_file(
        url=f'https://files.pythonhosted.org/packages/source/u/ubo_app/ubo_app-{target_version}.tar.gz',
        path=UPDATE_ASSETS_PATH / 'package.tar.gz',
    ):
        store.dispatch(
            NotificationsAddAction(
                notification=replace(
                    UPDATE_PROGRESS_NOTIFICATION,
                    progress=(report[0] / report[1]) * 0.05 if report[1] else 0,
                ),
            ),
        )

    with tarfile.open(
        UPDATE_ASSETS_PATH / 'package.tar.gz',
        'r:gz',
    ) as tar:
        install_file_info = next(
            (
                m
                for m in tar.getmembers()
                if m.name.endswith('ubo_app/system/scripts/install.sh')
            ),
            None,
        )
        if not install_file_info:
            msg = 'Failed to extract install.sh'
            raise RuntimeError(msg)
        install_file_info.name = 'install.sh'
        tar.extract(install_file_info, path=UPDATE_ASSETS_PATH)

    (UPDATE_ASSETS_PATH / 'install.sh').chmod(0o755)

    store.dispatch(
        NotificationsAddAction(
            notification=replace(
                UPDATE_PROGRESS_NOTIFICATION,
                content='Running the `install.sh` script...',
                progress=0.06,
            ),
        ),
    )

    def handle_package_collection_progress(line: str) -> tuple[float, str]:
        """Handle package collection progress."""
        nonlocal counter
        counter += 1
        package_name = line.partition(' ')[2].strip()
        return (
            min((counter + 1) / packages_count, 1) * 0.3 + 0.2,
            f'Downloading {package_name}',
        )

    progress_map: dict[str, tuple[float, str] | Callable[[str], tuple[float, str]]] = {
        'Installing dependencies...': (0.07, 'Installing system dependencies...'),
        'Setting up Python virtual environment...': (
            0.19,
            'Setting up Python virtual environment...',
        ),
        'Installing packages...': (0.2, 'Installing Python packages...'),
        'Collecting ': handle_package_collection_progress,
        'Installing collected packages: ': (
            0.51,
            'Installing collected packages...',
        ),
        'ubo-app installed successfully in ': (
            0.7,
            'ubo-app package installed successfully.',
        ),
        'Installing WM8960 driver...': (0.71, 'Installing WM8960 driver...'),
        'WM8960 driver installed successfully.': (
            0.8,
            'WM8960 driver installed successfully.',
        ),
        'Installing Docker...': (0.81, 'Installing Docker...'),
        'Docker installed successfully.': (
            0.9,
            'Docker installed successfully.',
        ),
        'Bootstrapping ubo-app...': (0.9, 'Bootstrapping ubo-app...'),
        'Bootstrapping completed': (1, 'Bootstrapping completed'),
    }

    async for line in await send_command(
        'update',
        target_version or '',
        has_output_stream=True,
    ):
        for key, report_ in progress_map.items():
            if line.startswith(key):
                report = report_(line) if callable(report_) else report_
                progress, message = report
                store.dispatch(
                    NotificationsAddAction(
                        notification=replace(
                            UPDATE_PROGRESS_NOTIFICATION,
                            content=message,
                            progress=progress,
                        ),
                    ),
                )
                if progress == 1:
                    await asyncio.sleep(1)
                    break
        else:
            continue
        break
    else:
        msg = 'Failed to update: install script failed, check system manager logs.'
        logger.info(msg)
        raise RuntimeError(msg)

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=UPDATE_MANAGER_NOTIFICATION_ID,
                title='Update Complete',
                content="""\
Ubo App will restart now.""",
                extra_information=ReadableInformation(
                    text='In a few seconds, the ubo app should restart itself and run '
                    'the newly installed version.',
                ),
                display_type=NotificationDisplayType.STICKY,
                color=SUCCESS_COLOR,
                icon='󰄬',
                progress=1,
                show_dismiss_action=False,
            ),
        ),
    )


async def update(event_request_event: UpdateManagerUpdateEvent) -> None:
    """Update the Ubo app."""
    logger.info('Updating Ubo app...')
    target_version = event_request_event.version

    if target_version is None:
        return

    try:
        await _update(target_version)
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


def activate_version(version: Path) -> None:
    """Activate the selected version."""
    logger.info('Activating version %s', version.name)
    if not version.is_dir():
        return

    env_path = Path(INSTALLATION_PATH) / 'env'
    env_path.unlink(missing_ok=True)
    env_path.symlink_to(version, target_is_directory=True)

    store.dispatch(FinishAction())


def open_about_menu() -> HeadedMenu:
    """Get the about menu items."""
    store.dispatch(UpdateManagerRequestCheckAction())

    return HeadedMenu(
        title='About',
        heading=f'Ubo v{CURRENT_VERSION}',
        sub_heading=f'Base image: {BASE_IMAGE[:11]}\n{BASE_IMAGE[11:]}',
        items=about_menu_items,
    )


@store.autorun(lambda state: (state.update_manager, state.settings.beta_versions))
def about_menu_items(data: tuple[UpdateManagerState, bool]) -> list[Item]:
    """Get the update menu items."""
    state, beta_versions = data
    items: list[Item] = []

    recent_versions_item = SubMenuItem(
        key='recent_versions',
        label='Recent versions',
        icon='󰜉',
        sub_menu=HeadlessMenu(
            title='󰜉Recent versions',
            items=[
                UboDispatchItem(
                    label=version,
                    icon='󰜉',
                    store_action=NotificationsAddAction(
                        notification=Notification(
                            title=f'Install {version} now?',
                            content='Press 󰜉 button to start installation of version '
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
                )
                for version in state.recent_versions
            ],
        ),
    )

    installed_versions_item = SubMenuItem(
        key='installed_versions',
        label='Installed versions',
        icon='󰯍',
        sub_menu=HeadlessMenu(
            title='󰯍Installed versions',
            items=[
                UboDispatchItem(
                    label=item.name,
                    **(
                        SELECTED_ITEM_PARAMETERS
                        if item.name == CURRENT_VERSION
                        else UNSELECTED_ITEM_PARAMETERS
                    ),
                    store_action=NotificationsAddAction(
                        notification=Notification(
                            title=f'Activate {item.name} now?',
                            content=f'Press 󰯍 button to activate version "{item.name}"',
                            icon='󰯍',
                            extra_information=ReadableInformation(
                                text="""Do you want to activate the selected version of
    ubo-app?""",
                            ),
                            color=INFO_COLOR,
                            dismiss_on_close=True,
                            display_type=NotificationDisplayType.STICKY,
                            show_dismiss_action=True,
                            actions=[
                                NotificationActionItem(
                                    icon='󰯍',
                                    action=functools.partial(
                                        activate_version,
                                        version=item,
                                    ),
                                ),
                            ],
                        ),
                    ),
                )
                for item in get_installed_versions()
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
            UboDispatchItem(
                label='Failed to check for updates',
                store_action=UpdateManagerRequestCheckAction(),
                icon='󰜺',
                background_color=DANGER_COLOR,
            ),
        ]
    if state.update_status is UpdateStatus.UP_TO_DATE:
        items = [
            UboDispatchItem(
                label='Already up to date!',
                icon='󰄬',
                store_action=UpdateManagerRequestCheckAction(),
                background_color=SUCCESS_COLOR,
                color='#000000',
            ),
            recent_versions_item,
        ]
        if beta_versions:
            items.append(installed_versions_item)
    if state.update_status is UpdateStatus.OUTDATED:
        items = [
            *(
                []
                if state.latest_version is None
                else [
                    UboDispatchItem(
                        label=f'Update to v{state.latest_version}',
                        icon='󰬬',
                        store_action=NotificationsAddAction(
                            notification=Notification(
                                title=f'Install {state.latest_version} now?',
                                content='Press 󰬬 button to start installation of '
                                f'version "{state.latest_version}"',
                                icon='󰬬',
                                extra_information=ReadableInformation(
                                    text='Do you want to update to the latest version?',
                                ),
                                color=INFO_COLOR,
                                dismiss_on_close=True,
                                display_type=NotificationDisplayType.STICKY,
                                show_dismiss_action=True,
                                actions=[
                                    NotificationDispatchItem(
                                        icon='󰬬',
                                        store_action=UpdateManagerRequestUpdateAction(
                                            version=state.latest_version,
                                        ),
                                    ),
                                ],
                            ),
                        ),
                    ),
                ]
            ),
            recent_versions_item,
        ]
        if beta_versions:
            items.append(installed_versions_item)
    if state.update_status is UpdateStatus.UPDATING:
        items = [
            Item(
                label='Updating...',
                icon='󰇚',
                background_color='#00000000',
            ),
        ]

    return items
