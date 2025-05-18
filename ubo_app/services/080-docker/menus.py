"""Menus and actions for Docker images."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docker_composition import (
    check_composition,
)
from docker_container import check_container
from docker_images import IMAGES
from docker_qrcode_page import DockerQRCodePage
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
                label='Fetch',
                icon='󰇚',
                store_action=DockerImageFetchAction(image=image.id),
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
                    if image.id.startswith('composition_')
                    else DockerImageRunContainerAction(image=image.id),
                ),
                *(
                    [
                        UboDispatchItem(
                            label='Pull Images',
                            icon='󰇚',
                            store_action=DockerImageFetchCompositionAction(
                                image=image.id,
                            ),
                        ),
                    ]
                    if image.id.startswith('composition_')
                    else []
                ),
                UboDispatchItem(
                    label='Delete Application'
                    if image.id.startswith('composition_')
                    else 'Remove Image',
                    icon='󰆴',
                    store_action=DockerImageRemoveCompositionAction(image=image.id)
                    if image.id.startswith('composition_')
                    else DockerImageRemoveAction(image=image.id),
                    background_color=DANGER_COLOR
                    if image.id.startswith('composition_')
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
                    if image.id.startswith('composition_')
                    else DockerImageRunContainerAction(image=image.id),
                ),
                UboDispatchItem(
                    label='Release Resources'
                    if image.id.startswith('composition_')
                    else 'Remove Container',
                    icon='󰆴',
                    store_action=DockerImageReleaseCompositionAction(image=image.id)
                    if image.id.startswith('composition_')
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
                if image.id.startswith('composition_')
                else DockerImageStopContainerAction(image=image.id),
            ),
        )
        if image.id.startswith('composition_'):
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

    if image.id.startswith('composition_'):
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
        messages = {
            DockerItemStatus.NOT_AVAILABLE: 'Need to fetch the image',
            DockerItemStatus.FETCHING: 'Image is being fetched',
            DockerItemStatus.AVAILABLE: 'Image is ready but container is not running',
            DockerItemStatus.CREATED: 'Container is created but not running',
            DockerItemStatus.RUNNING: IMAGES[image.id].note or 'Container is running',
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
    if image_id.startswith('composition_'):
        create_task(check_composition(id=image_id))
    else:
        check_container(image_id=image_id)

    return store.autorun(
        lambda state: getattr(state.docker, image_id),
        lambda state: (
            getattr(state.docker, image_id),
            state.ip.interfaces if hasattr(state, 'ip') else None,
        ),
    )(image_menu)
