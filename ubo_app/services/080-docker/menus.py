"""Menus and actions for Docker images."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docker_composition import check_composition
from docker_container import check_container
from docker_images import IMAGES, configure_twingate, is_twingate_configured
from redux import AutorunOptions

from ubo_app.colors import DANGER_COLOR
from ubo_app.constants import SECRETS_PATH
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuItemData,
    OpenRenderAction,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageFetchAction,
    DockerImageReleaseAction,
    DockerImageRemoveAction,
    DockerImageRemoveContainerAction,
    DockerImageRunAction,
    DockerImageStopAction,
    DockerItemStatus,
    ImageState,
)
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.services.ip import IpNetworkInterface


def _secrets_modification_time() -> float:
    """Return the modification time of the secrets file."""
    return SECRETS_PATH.stat().st_mtime if SECRETS_PATH.exists() else 0


def _open_twingate_configure() -> None:
    """Open the Twingate configuration dialog."""
    create_task(configure_twingate())


def get_docker_image_menu_id(image_id: str) -> str:
    """Get the dynamic menu ID for a Docker image."""
    return f'docker:image:{image_id}'


def _show_delete_confirmation(image_id: str) -> None:
    """Show confirmation dialog before deleting a composition."""
    def _delete_action() -> None:
        """Execute the delete action."""
        store.dispatch(DockerImageRemoveAction(image=image_id))

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='Delete Application?',
                content='All application data and files will be permanently deleted. '
                'This action cannot be undone.',
                importance=Importance.HIGH,
                icon='󰆴',
                actions=[
                    create_notification_action(
                        action=_delete_action,
                        icon='󰆴',
                        background_color=DANGER_COLOR,
                        label='Delete',
                    ),
                ],
            ),
        ),
    )


_image_action_ids: dict[str, list[str]] = {}


def _update_docker_image_menu(  # noqa: C901, PLR0912, PLR0915
    image: ImageState,
    interfaces: Sequence[IpNetworkInterface] | None,
) -> None:
    """Update the dynamic menu for a docker image."""
    menu_id = get_docker_image_menu_id(image.id)
    is_composition = image.id in IMAGES and IMAGES[image.id].is_composition

    # Clean up old actions
    for action_id in _image_action_ids.get(menu_id, []):
        unregister_action(action_id)
    _image_action_ids[menu_id] = []

    ip_addresses = [
        ip for interface in interfaces or [] for ip in interface.ip_addresses
    ]
    items: list[MenuItemData] = []

    if image.status == DockerItemStatus.NOT_AVAILABLE:
        action_id = f'docker:fetch:{image.id}'
        _image_action_ids[menu_id].append(action_id)
        register_action(
            action_id,
            lambda _id=image.id: store.dispatch(DockerImageFetchAction(image=_id)),
        )
        items.append(
            MenuItemData(
                key='fetch',
                label='Pull Images' if is_composition else 'Fetch',
                icon='󰇚',
                action_id=action_id,
            ),
        )
    elif image.status == DockerItemStatus.FETCHING:
        pass
    elif image.status == DockerItemStatus.AVAILABLE:
        start_id = f'docker:start:{image.id}'
        _image_action_ids[menu_id].append(start_id)
        register_action(
            start_id,
            lambda _id=image.id: store.dispatch(DockerImageRunAction(image=_id)),
        )
        items.append(
            MenuItemData(
                key='start',
                label='Start',
                icon='󰐊',
                action_id=start_id,
            ),
        )

        if image.id == 'twingate' and is_twingate_configured():
            reconfigure_id = f'docker:reconfigure:{image.id}'
            _image_action_ids[menu_id].append(reconfigure_id)
            register_action(reconfigure_id, _open_twingate_configure)
            items.append(
                MenuItemData(
                    key='reconfigure',
                    label='Reconfigure',
                    icon='󰒓',
                    action_id=reconfigure_id,
                ),
            )

        if is_composition:
            delete_id = f'docker:delete:{image.id}'
            _image_action_ids[menu_id].append(delete_id)
            register_action(
                delete_id,
                lambda _id=image.id: _show_delete_confirmation(_id),
            )
            items.append(
                MenuItemData(
                    key='delete',
                    label='Delete Application',
                    icon='󰆴',
                    background_color=DANGER_COLOR,
                    action_id=delete_id,
                ),
            )
        else:
            remove_id = f'docker:remove:{image.id}'
            _image_action_ids[menu_id].append(remove_id)
            register_action(
                remove_id,
                lambda _id=image.id: store.dispatch(
                    DockerImageRemoveAction(image=_id),
                ),
            )
            items.append(
                MenuItemData(
                    key='remove',
                    label='Remove Image',
                    icon='󰆴',
                    background_color=DANGER_COLOR,
                    action_id=remove_id,
                ),
            )
    elif image.status == DockerItemStatus.CREATED:
        start_id = f'docker:start:{image.id}'
        _image_action_ids[menu_id].append(start_id)
        register_action(
            start_id,
            lambda _id=image.id: store.dispatch(DockerImageRunAction(image=_id)),
        )
        items.append(
            MenuItemData(
                key='start',
                label='Start',
                icon='󰐊',
                action_id=start_id,
            ),
        )

        if image.id == 'twingate' and is_twingate_configured():
            reconfigure_id = f'docker:reconfigure:{image.id}'
            _image_action_ids[menu_id].append(reconfigure_id)
            register_action(reconfigure_id, _open_twingate_configure)
            items.append(
                MenuItemData(
                    key='reconfigure',
                    label='Reconfigure',
                    icon='󰒓',
                    action_id=reconfigure_id,
                ),
            )

        release_id = f'docker:release:{image.id}'
        _image_action_ids[menu_id].append(release_id)
        if is_composition:
            register_action(
                release_id,
                lambda _id=image.id: store.dispatch(
                    DockerImageReleaseAction(image=_id),
                ),
            )
            items.append(
                MenuItemData(
                    key='release',
                    label='Release Resources',
                    icon='󰆴',
                    action_id=release_id,
                ),
            )
        else:
            register_action(
                release_id,
                lambda _id=image.id: store.dispatch(
                    DockerImageRemoveContainerAction(image=_id),
                ),
            )
            items.append(
                MenuItemData(
                    key='remove_container',
                    label='Remove Container',
                    icon='󰆴',
                    background_color=DANGER_COLOR,
                    action_id=release_id,
                ),
            )
    elif image.status == DockerItemStatus.RUNNING:
        stop_id = f'docker:stop:{image.id}'
        _image_action_ids[menu_id].append(stop_id)
        register_action(
            stop_id,
            lambda _id=image.id: store.dispatch(DockerImageStopAction(image=_id)),
        )
        items.append(
            MenuItemData(
                key='stop',
                label='Stop',
                icon='󰓛',
                action_id=stop_id,
            ),
        )

        if is_composition:
            if image.instructions:
                instructions_id = f'docker:instructions:{image.id}'
                _image_action_ids[menu_id].append(instructions_id)
                register_action(
                    instructions_id,
                    lambda _img=image: store.dispatch(
                        NotificationsAddAction(
                            notification=Notification(
                                icon='󰋗',
                                title='Instructions',
                                content='',
                                extra_information=ReadableInformation(
                                    text=_img.instructions,
                                )
                                if _img.instructions
                                else None,
                            ),
                        ),
                    ),
                )
                items.append(
                    MenuItemData(
                        key='instructions',
                        label='Instructions',
                        icon='󰋗',
                        action_id=instructions_id,
                    ),
                )
        else:
            # Ports submenu navigation
            ports_nav_id = f'docker:open-ports:{image.id}'
            _image_action_ids[menu_id].append(ports_nav_id)
            register_action(
                ports_nav_id,
                lambda: store.dispatch(
                    StackPushMenuAction(menu_key='ports'),
                ),
            )
            items.append(
                MenuItemData(
                    key='ports',
                    label='Ports',
                    icon='󰙜',
                    action_id=ports_nav_id,
                ),
            )

            # Build ports submenu
            port_items: list[MenuItemData] = []
            for port in image.ports:
                if port.startswith('0.0.0.0'):  # noqa: S104
                    port_action_id = f'docker:qrcode:{image.id}:{port}'
                    _image_action_ids[menu_id].append(port_action_id)
                    port_number = port.split(':')[-1]
                    register_action(
                        port_action_id,
                        lambda _port=port_number, _ips=ip_addresses: store.dispatch(
                            OpenRenderAction(
                                kind='qr_code_carousel',
                                title='Docker Port',
                                props={
                                    'values': tuple(
                                        f'http://{ip}:{_port}/' for ip in _ips
                                    ),
                                    'labels': tuple(
                                        f'{ip}:{_port}' for ip in _ips
                                    ),
                                },
                            ),
                        ),
                    )
                    port_items.append(
                        MenuItemData(
                            key=port,
                            label=port,
                            icon='󰙜',
                            action_id=port_action_id,
                        ),
                    )
                else:
                    port_items.append(
                        MenuItemData(
                            key=port,
                            label=port,
                            icon='󰙜',
                        ),
                    )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'docker:image:{image.id}:ports',
                    title='Ports',
                    items=tuple(port_items),
                    placeholder='No ports',
                ),
            )
    elif image.status == DockerItemStatus.PROCESSING:
        pass

    # Status messages
    if is_composition:
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

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=menu_id,
            title=f'Docker - {image.label}',
            heading=image.label,
            sub_heading=messages[image.status],
            items=tuple(items),
            placeholder='',
        ),
    )


def setup_docker_image_dynamic_menu(image_id: str) -> None:
    """Set up dynamic menu updates for a Docker image."""
    has_secrets = image_id in IMAGES and bool(IMAGES[image_id].secret_keys)

    @store.autorun(
        lambda state: getattr(state.docker, image_id, None),
        lambda state: (
            getattr(state.docker, image_id, None),
            state.ip.interfaces if hasattr(state, 'ip') else None,
            _secrets_modification_time() if has_secrets else None,
        ),
        options=AutorunOptions(default_value=None, memoization=not has_secrets),
    )
    def update_dynamic_menu(image: ImageState | None) -> None:
        """Update the dynamic menu when image state changes."""
        if image is None:
            return

        # Check status if not in middle of an operation
        if image.status not in (DockerItemStatus.FETCHING, DockerItemStatus.PROCESSING):
            is_composition = image_id in IMAGES and IMAGES[image_id].is_composition
            if is_composition:
                create_task(check_composition(id=image_id))
            else:
                check_container(image_id=image_id)

        @store.with_state(
            lambda state: state.ip.interfaces if hasattr(state, 'ip') else None,
        )
        def _get_interfaces(
            interfaces: Sequence[IpNetworkInterface] | None,
        ) -> Sequence[IpNetworkInterface] | None:
            return interfaces

        _update_docker_image_menu(image, _get_interfaces())


def docker_item_menu(image_id: str) -> None:
    """Navigate to the Docker image menu."""
    # menu_key uses 'docker:<image_id>' format to match the path matcher,
    # which maps it to the dynamic menu ID 'docker:image:<image_id>'
    store.dispatch(StackPushMenuAction(menu_key=f'docker:{image_id}'))
