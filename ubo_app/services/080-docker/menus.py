"""Menus and actions for Docker images."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from apps import IMAGES
from docker_composition import check_composition
from docker_container import check_container
from docker_logs import PLACEHOLDER as LOGS_PLACEHOLDER
from docker_logs import stream_id as logs_stream_id
from redux import AutorunOptions

from ubo_app.colors import DANGER_COLOR
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
    DockerImageSetExposeToLanAction,
    DockerImageSetStatusAction,
    DockerImageStopAction,
    DockerItemHealth,
    DockerItemStatus,
    ImageState,
    derive_health,
)
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def _health_message(image: ImageState, health: DockerItemHealth) -> str:
    """Say what the app did, in the space the status message would have used."""
    cause = image.last_error or (
        f'exit {image.last_exit_code}' if image.last_exit_code is not None else ''
    )
    if health is DockerItemHealth.CRASH_LOOPING:
        headline = f'Keeps crashing — {image.restart_count} restarts'
    else:
        plural = '' if image.restart_count == 1 else 's'
        headline = f'Restarted {image.restart_count} time{plural}'
    return f'{headline} ({cause}) — open Logs' if cause else f'{headline} — open Logs'


def _update_docker_image_menu(  # noqa: C901, PLR0912, PLR0915
    image: ImageState,
    interfaces: Sequence[IpNetworkInterface] | None,
    *,
    expose_to_lan: bool,
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

        # App-specific menu actions (e.g., Reconfigure, Show token)
        if (hook := IMAGES.get(image.id, None)) and hook.menu_actions:
            hook.menu_actions(menu_id, items, _image_action_ids)

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

        if (hook := IMAGES.get(image.id, None)) and hook.menu_actions:
            hook.menu_actions(menu_id, items, _image_action_ids)

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
    elif image.status in (DockerItemStatus.STARTING, DockerItemStatus.RUNNING):
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

        if (hook := IMAGES.get(image.id, None)) and hook.menu_actions:
            hook.menu_actions(menu_id, items, _image_action_ids)

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

    # LAN exposure toggle for apps with weak/no auth (loopback by default).
    entry = IMAGES.get(image.id)
    if (
        entry is not None
        and entry.supports_lan_toggle
        and image.status
        in (
            DockerItemStatus.AVAILABLE,
            DockerItemStatus.CREATED,
            DockerItemStatus.STARTING,
            DockerItemStatus.RUNNING,
        )
    ):
        toggle_id = f'docker:toggle-lan:{image.id}'
        _image_action_ids[menu_id].append(toggle_id)
        register_action(
            toggle_id,
            lambda _id=image.id, _exposed=expose_to_lan: store.dispatch(
                DockerImageSetExposeToLanAction(image=_id, expose_to_lan=not _exposed),
            ),
        )
        items.append(
            MenuItemData(
                key='toggle-lan',
                label='Loopback only' if expose_to_lan else 'Expose to LAN',
                icon='󰒋' if expose_to_lan else '󰌐',
                action_id=toggle_id,
            ),
        )

    # Logs, wherever there is something that could have produced any. Offered
    # in ERROR too — that is the state whose message tells the user to go read
    # them, and until now there was nowhere to go.
    if image.status in (
        DockerItemStatus.CREATED,
        DockerItemStatus.STARTING,
        DockerItemStatus.RUNNING,
        DockerItemStatus.ERROR,
    ):
        logs_id = f'docker:logs:{image.id}'
        _image_action_ids[menu_id].append(logs_id)
        register_action(
            logs_id,
            lambda _id=image.id, _label=image.label: store.dispatch(
                OpenRenderAction(
                    kind='text_viewer',
                    title=f'{_label} Logs',
                    stream_id=logs_stream_id(_id),
                    # The tail arrives from `docker_logs`' polling loop, which
                    # starts when this page reaches the top of the stack.
                    props={'text': LOGS_PLACEHOLDER},
                ),
            ),
        )
        items.append(
            MenuItemData(
                key='logs',
                label='Logs',
                icon='󰦪',
                action_id=logs_id,
            ),
        )

    # Status messages
    if is_composition:
        messages = {
            DockerItemStatus.NOT_AVAILABLE: 'Need to fetch images',
            DockerItemStatus.FETCHING: 'Images are being fetched',
            DockerItemStatus.AVAILABLE: 'Images are ready but composition is not '
            'running',
            DockerItemStatus.CREATED: 'Composition is created but not running',
            DockerItemStatus.STARTING: 'Application is starting...',
            DockerItemStatus.RUNNING: 'Composition is running',
            DockerItemStatus.ERROR: 'Something went wrong — open Logs for details',
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
            DockerItemStatus.STARTING: 'Application is starting...',
            DockerItemStatus.RUNNING: running_message or 'Container is running',
            DockerItemStatus.ERROR: 'Something went wrong — open Logs for details',
            DockerItemStatus.PROCESSING: 'Waiting...',
        }

    # The terminal destructive item ("Delete Application" / "Remove Image" /
    # "Remove Container") must always be the last item in every app menu,
    # regardless of where it (or items like the LAN toggle) were appended above.
    # `list.sort` is stable, so the relative order of all other items is kept.
    items.sort(key=lambda item: item.key in ('delete', 'remove', 'remove_container'))

    # A crash record outranks the lifecycle message. With `restart_policy:
    # always` a failing app reads as "running" seconds after it died, so the
    # lifecycle status alone would keep saying everything is fine.
    health = derive_health(image, now=time.time())
    sub_heading = (
        messages[image.status]
        if health is DockerItemHealth.OK
        else _health_message(image, health)
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=menu_id,
            title=f'Docker - {image.label}',
            heading=image.label,
            sub_heading=sub_heading,
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
            state.docker.service.expose_to_lan.get(image_id, False),
            secrets.modification_time() if has_secrets else None,
        ),
        options=AutorunOptions(default_value=None, memoization=not has_secrets),
    )
    def update_dynamic_menu(image: ImageState | None) -> None:
        """Update the dynamic menu when image state changes."""
        if image is None:
            return

        @store.with_state(
            lambda state: state.ip.interfaces if hasattr(state, 'ip') else None,
        )
        def _get_interfaces(
            interfaces: Sequence[IpNetworkInterface] | None,
        ) -> Sequence[IpNetworkInterface] | None:
            return interfaces

        @store.with_state(lambda state: state.docker.service.expose_to_lan)
        def _get_expose_to_lan(expose_to_lan: dict[str, bool]) -> bool:
            return expose_to_lan.get(image_id, False)

        _update_docker_image_menu(
            image,
            _get_interfaces(),
            expose_to_lan=_get_expose_to_lan(),
        )

        if (
            image.status == DockerItemStatus.STARTING
            and image_id in IMAGES
            and IMAGES[image_id].ports
        ):
            from port_monitor import _first_host_port, monitor_app_port

            host_port = _first_host_port(IMAGES[image_id].ports)
            if host_port:
                create_task(monitor_app_port(image_id, host_port))
            else:
                store.dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=DockerItemStatus.RUNNING,
                    ),
                )
        elif (
            image.status == DockerItemStatus.STARTING
            and (image_id not in IMAGES or not IMAGES[image_id].ports)
        ):
            store.dispatch(
                DockerImageSetStatusAction(
                    image=image_id,
                    status=DockerItemStatus.RUNNING,
                ),
            )


def docker_item_menu(image_id: str) -> None:
    """Navigate to the Docker image menu and refresh its container state."""
    if image_id in IMAGES and IMAGES[image_id].is_composition:
        create_task(check_composition(id=image_id))
    else:
        check_container(image_id=image_id)
    store.dispatch(StackPushMenuAction(menu_key=f'docker:{image_id}'))
