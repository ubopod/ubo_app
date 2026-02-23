"""Menus and actions for Docker images."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docker_composition import check_composition
from docker_container import check_container
from docker_images import IMAGES
from redux import AutorunOptions
from ubo_gui.menu.types import (
    ActionItem,
    HeadedMenu,
    HeadlessMenu,
    Item,
    SubMenuItem,
)

from ubo_app.colors import DANGER_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    OpenApplicationAction,
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
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationActionItem,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_app.store.services.ip import IpNetworkInterface


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
                    NotificationActionItem(
                        action=_delete_action,
                        icon='󰆴',
                        background_color=DANGER_COLOR,
                        label='Delete',
                    ),
                ],
            ),
        ),
    )


@store.with_state(lambda state: state.ip.interfaces if hasattr(state, 'ip') else None)
def image_menu(  # noqa: C901
    interfaces: Sequence[IpNetworkInterface] | None,
    image: ImageState,
) -> HeadedMenu:
    """Get the menu for the docker image."""
    ip_addresses = [
        ip for interface in interfaces or [] for ip in interface.ip_addresses
    ]
    items: list[Item] = []
    is_composition = image.id in IMAGES and IMAGES[image.id].is_composition

    def open_qrcode(port: str) -> Callable[[], None]:
        def action() -> None:
            import json

            store.dispatch(
                OpenApplicationAction(
                    application_id='docker:qrcode-page',
                    initialization_kwargs={
                        'ips': json.dumps(ip_addresses),
                        'port': port,
                    },
                ),
            )

        return action

    if image.status == DockerItemStatus.NOT_AVAILABLE:
        items.append(
            UboDispatchItem(
                label='Pull Images' if is_composition else 'Fetch',
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
                    store_action=DockerImageRunAction(image=image.id),
                ),
                ActionItem(
                    label='Delete Application' if is_composition else 'Remove Image',
                    icon='󰆴',
                    background_color=DANGER_COLOR,
                    action=lambda img_id=image.id: _show_delete_confirmation(img_id),
                ) if is_composition else UboDispatchItem(
                    label='Remove Image',
                    icon='󰆴',
                    store_action=DockerImageRemoveAction(image=image.id),
                    background_color=DANGER_COLOR,
                ),
            ],
        )
    elif image.status == DockerItemStatus.CREATED:
        items.extend(
            [
                UboDispatchItem(
                    label='Start',
                    icon='󰐊',
                    store_action=DockerImageRunAction(image=image.id),
                ),
                UboDispatchItem(
                    label='Release Resources' if is_composition else 'Remove Container',
                    icon='󰆴',
                    store_action=DockerImageReleaseAction(image=image.id)
                    if is_composition
                    else DockerImageRemoveContainerAction(image=image.id),
                    background_color=DANGER_COLOR if not is_composition else None,
                ),
            ],
        )
    elif image.status == DockerItemStatus.RUNNING:
        items.append(
            UboDispatchItem(
                label='Stop',
                key='stop',
                icon='󰓛',
                store_action=DockerImageStopAction(image=image.id),
            ),
        )
        if is_composition:
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
                            if port.startswith('0.0.0.0') and ip_addresses  # noqa: S104
                            else Item(label=port, icon='󰙜')
                            for port in image.ports
                        ],
                        placeholder='No ports',
                    ),
                ),
            )
    elif image.status == DockerItemStatus.PROCESSING:
        pass

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
        # For containers, use note from IMAGES
        # For compositions, use generic message
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


def _convert_item_to_menu_item_data(
    item: Item,
    index: int,
    image_id: str,
) -> MenuItemData:
    """Convert a ubo_gui Item to MenuItemData for dynamic menus."""
    # Get key
    key_val = getattr(item, 'key', None)
    key = key_val if isinstance(key_val, str) else f'item_{index}'

    # Get label
    label_val = getattr(item, 'label', '')
    label = label_val() if callable(label_val) else (label_val or '')

    # Get icon
    icon_val = getattr(item, 'icon', '')
    icon = icon_val() if callable(icon_val) else (icon_val or '')

    # Get background_color
    bg_color_val = getattr(item, 'background_color', None)
    bg_color: str | None = bg_color_val if isinstance(bg_color_val, str) else None

    # Determine action_id based on item type
    action_id: str | None = None

    # Check for store_action (UboDispatchItem)
    store_action = getattr(item, 'store_action', None)
    if store_action is not None:
        from ubo_app.store.core.action_registry import register_action, unregister_action

        action_type = type(store_action).__name__
        action_id = f'docker:{image_id}:{action_type}'

        # Register a handler so ExecuteMenuActionAction can dispatch it
        unregister_action(action_id)
        captured_action = store_action

        def _handler(action: object = captured_action) -> None:
            store.dispatch(action)

        register_action(action_id, _handler)
    elif key_val:
        action_id = f'docker:{image_id}:select:{key}'

    return MenuItemData(
        key=key,
        label=str(label),
        icon=str(icon),
        action_id=action_id,
        background_color=bg_color,
    )


def setup_docker_image_dynamic_menu(image_id: str) -> None:
    """Set up dynamic menu updates for a Docker image.

    This creates an autorun that watches the image state and dispatches
    UpdateDynamicMenuAction when it changes. This ensures TUI gets
    up-to-date menu state without coupling core to Docker service.
    """
    menu_id = get_docker_image_menu_id(image_id)

    @store.autorun(
        lambda state: getattr(state.docker, image_id, None),
        lambda state: (
            getattr(state.docker, image_id, None),
            state.ip.interfaces if hasattr(state, 'ip') else None,
        ),
        options=AutorunOptions(default_value=None),
    )
    def update_dynamic_menu(image: ImageState | None) -> None:
        """Update the dynamic menu when image state changes."""
        if image is None:
            return

        # Get the menu from image_menu (same logic as GUI uses)
        menu = image_menu(image)

        # Resolve callable fields (HeadedMenu fields can be callables)
        items_raw = menu.items
        items_list = items_raw() if callable(items_raw) else items_raw

        title_raw = menu.title
        title = title_raw() if callable(title_raw) else (title_raw or '')

        heading_raw = menu.heading
        heading = heading_raw() if callable(heading_raw) else heading_raw

        sub_heading_raw = menu.sub_heading
        sub_heading = (
            sub_heading_raw() if callable(sub_heading_raw) else sub_heading_raw
        )

        placeholder_raw = menu.placeholder
        placeholder = (
            placeholder_raw() if callable(placeholder_raw) else placeholder_raw
        )

        # Convert menu items to MenuItemData
        menu_items = tuple(
            _convert_item_to_menu_item_data(item, i, image_id)
            for i, item in enumerate(items_list)
            if item is not None
        )

        logger.debug(
            '[Docker] Updating dynamic menu for %s: status=%s, items=%d',
            image_id,
            image.status,
            len(menu_items),
        )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=menu_id,
                title=str(title),
                heading=str(heading) if heading else None,
                sub_heading=str(sub_heading) if sub_heading else None,
                items=menu_items,
                placeholder=str(placeholder) if placeholder else '',
            ),
        )


def docker_item_menu(image_id: str) -> Callable[[], HeadedMenu]:
    """Get the menu items for the Docker service."""
    # Don't check status during ongoing operations (FETCHING, PROCESSING)
    # The operation itself manages the status
    def menu_with_check(image: ImageState) -> HeadedMenu:
        # Only check status if not in middle of an operation
        if image.status not in (DockerItemStatus.FETCHING, DockerItemStatus.PROCESSING):
            is_composition = image_id in IMAGES and IMAGES[image_id].is_composition
            if is_composition:
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
