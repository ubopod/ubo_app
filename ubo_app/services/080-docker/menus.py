"""Menus and actions for Docker images."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docker_composition import COMPOSITIONS_PATH, check_composition
from docker_container import check_container
from docker_images import IMAGES
from docker_presets import PRESET_COMPOSITIONS
from docker_qrcode_page import DockerQRCodePage
from redux import AutorunOptions
from ubo_gui.menu.types import (
    ActionItem,
    HeadedMenu,
    HeadlessMenu,
    Item,
    SubMenuItem,
)

from ubo_app.colors import DANGER_COLOR
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageFetchAction,
    DockerImageFetchCompositionAction,
    DockerImageReleaseCompositionAction,
    DockerImageRemoveAction,
    DockerImageRemoveCompositionAction,
    DockerImageRemoveContainerAction,
    DockerImageRunCompositionAction,
    DockerImageRunContainerAction,
    DockerImageStopCompositionAction,
    DockerImageStopContainerAction,
    DockerItemStatus,
    DockerPresetInstallAction,
    ImageState,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_gui.page import PageWidget

    from ubo_app.store.services.ip import IpNetworkInterface

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@store.with_state(lambda state: state.ip.interfaces if hasattr(state, 'ip') else None)
def image_menu(  # noqa: C901
    interfaces: Sequence[IpNetworkInterface] | None,
    image: ImageState,
) -> HeadedMenu:
    """Get the menu for the docker image."""
    interfaces = []
    ip_addresses = [
        ip for interface in interfaces or [] for ip in interface.ip_addresses
    ]
    items: list[Item] = []

    def open_qrcode(port: str) -> Callable[[], PageWidget]:
        def action() -> PageWidget:
            return DockerQRCodePage(ips=ip_addresses, port=port)

        return action

    if image.status == DockerItemStatus.NOT_AVAILABLE:
        items.append(
            UboDispatchItem(
                label='Pull Images' \
                    if image.id.startswith(('composition_', 'preset_')) \
                    else 'Fetch',
                icon='󰇚',
                store_action=DockerImageFetchCompositionAction(image=image.id)
                if image.id.startswith(('composition_', 'preset_'))
                else DockerImageFetchAction(image=image.id),
            ),
        )
    elif image.status == DockerItemStatus.FETCHING:
        pass
    elif image.status == DockerItemStatus.AVAILABLE:
        items.extend(
            [
                UboDispatchItem(
                    label='Start',
                    icon='󰐊',
                    store_action=DockerImageRunCompositionAction(image=image.id)
                    if image.id.startswith(('composition_', 'preset_'))
                    else DockerImageRunContainerAction(image=image.id),
                ),
                UboDispatchItem(
                    label='Delete Application'
                    if image.id.startswith(('composition_', 'preset_'))
                    else 'Remove Image',
                    icon='󰆴',
                    store_action=DockerImageRemoveCompositionAction(image=image.id)
                    if image.id.startswith(('composition_', 'preset_'))
                    else DockerImageRemoveAction(image=image.id),
                    background_color=DANGER_COLOR
                    if image.id.startswith(('composition_', 'preset_'))
                    else None,
                ),
            ],
        )
    elif image.status == DockerItemStatus.CREATED:
        items.extend(
            [
                UboDispatchItem(
                    label='Start',
                    icon='󰐊',
                    store_action=DockerImageRunCompositionAction(image=image.id)
                    if image.id.startswith(('composition_', 'preset_'))
                    else DockerImageRunContainerAction(image=image.id),
                ),
                UboDispatchItem(
                    label='Release Resources'
                    if image.id.startswith(('composition_', 'preset_'))
                    else 'Remove Container',
                    icon='󰆴',
                    store_action=DockerImageReleaseCompositionAction(image=image.id)
                    if image.id.startswith(('composition_', 'preset_'))
                    else DockerImageRemoveContainerAction(image=image.id),
                ),
            ],
        )
    elif image.status == DockerItemStatus.RUNNING:
        items.append(
            UboDispatchItem(
                label='Stop',
                key='stop',
                icon='󰓛',
                store_action=DockerImageStopCompositionAction(image=image.id)
                if image.id.startswith(('composition_', 'preset_'))
                else DockerImageStopContainerAction(image=image.id),
            ),
        )
        if image.id.startswith(('composition_', 'preset_')):
            items.append(
                UboDispatchItem(
                    label='Instructions',
                    key='instructions',
                    icon='󰋗',
                    store_action=NotificationsAddAction(
                        notification=Notification(
                            icon='󰋗',
                            title='Instructions',
                            content='',
                            extra_information=ReadableInformation(
                                text=image.instructions,
                            )
                            if image.instructions
                            else None,
                        ),
                    ),
                ),
            )
        else:
            items.append(
                SubMenuItem(
                    label='Ports',
                    key='ports',
                    icon='󰙜',
                    sub_menu=HeadlessMenu(
                        title='Ports',
                        items=[
                            ActionItem(
                                label=port,
                                key=port,
                                icon='󰙜',
                                action=open_qrcode(port.split(':')[-1]),
                            )
                            if port.startswith('0.0.0.0')  # noqa: S104
                            else Item(label=port, icon='󰙜')
                            for port in image.ports
                        ],
                        placeholder='No ports',
                    ),
                ),
            )
    elif image.status == DockerItemStatus.PROCESSING:
        pass

    if image.id.startswith(('composition_', 'preset_')):
        messages = {
            DockerItemStatus.NOT_AVAILABLE: 'Need to fetch images',
            DockerItemStatus.FETCHING: 'Images are being fetched',
            DockerItemStatus.AVAILABLE: 'Images are ready but composition is not '
            'running',
            DockerItemStatus.CREATED: 'Composition is created but not running',
            DockerItemStatus.RUNNING: 'Composition is running',
            DockerItemStatus.ERROR: 'We have an error, please check the logs',
            DockerItemStatus.PROCESSING: 'Waiting...',
        }
    else:
        # For containers, use note from IMAGES
        # For compositions/presets, use generic message
        running_message = (
            IMAGES[image.id].note
            if image.id in IMAGES
            else 'Container is running'
        )
        messages = {
            DockerItemStatus.NOT_AVAILABLE: 'Need to fetch the image',
            DockerItemStatus.FETCHING: 'Image is being fetched',
            DockerItemStatus.AVAILABLE: 'Image is ready but container is not running',
            DockerItemStatus.CREATED: 'Container is created but not running',
            DockerItemStatus.RUNNING: running_message or 'Container is running',
            DockerItemStatus.ERROR: 'We have an error, please check the logs',
            DockerItemStatus.PROCESSING: 'Waiting...',
        }

    return HeadedMenu(
        title=f'Docker - {image.label}',
        heading=image.label,
        sub_heading=messages[image.status],
        items=items,
        placeholder='',
    )


def docker_item_menu(image_id: str) -> Callable[[], HeadedMenu]:
    """Get the menu items for the Docker service."""
    # Don't check status during ongoing operations (FETCHING, PROCESSING)
    # The operation itself manages the status
    def menu_with_check(image: ImageState) -> HeadedMenu:
        # Only check status if not in middle of an operation
        if image.status not in (DockerItemStatus.FETCHING, DockerItemStatus.PROCESSING):
            if image_id.startswith(('composition_', 'preset_')):
                create_task(check_composition(id=image_id))
            else:
                check_container(image_id=image_id)
        return image_menu(image)

    return store.autorun(
        lambda state: getattr(state.docker, image_id),
        lambda state: (
            getattr(state.docker, image_id),
            state.ip.interfaces if hasattr(state, 'ip') else None,
        ),
        options=AutorunOptions(default_value=None),
    )(menu_with_check)


def docker_preset_menu(preset_id: str) -> Callable[[], HeadedMenu]:
    """Get menu for preset composition (for installation)."""
    preset = PRESET_COMPOSITIONS.get(preset_id)
    if not preset:
        # Return empty menu if preset not found
        return lambda: HeadedMenu(
            title='Docker',
            heading='Error',
            sub_heading='Preset not found',
            items=[],
        )

    composition_id = f'preset_{preset_id}'


    def preset_menu_func(image: ImageState | None) -> HeadedMenu:
        """Define a menu function that switches between install and normal menu."""
        # Check if composition directory actually exists
        composition_path = COMPOSITIONS_PATH / composition_id

        if image is not None and composition_path.exists():
            # Composition is installed - show the normal menu
            # Only check status if not in middle of an operation
            if image.status not in (
                DockerItemStatus.FETCHING,
                DockerItemStatus.PROCESSING,
            ):
                create_task(check_composition(id=composition_id))
            return image_menu(image)

        # Not installed yet, show install option
        return HeadedMenu(
            title=f'Docker - {preset.label}',
            heading=preset.label,
            sub_heading='Not installed',
            items=[
                UboDispatchItem(
                    label='Install',
                    icon='󰇚',
                    store_action=DockerPresetInstallAction(
                        preset_id=preset_id,
                    ),
                ),
            ],
        )

    # Watch the composition state and call preset_menu_func
    return store.autorun(
        lambda state: getattr(state.docker, composition_id, None),
        options=AutorunOptions(default_value=None),
    )(preset_menu_func)
