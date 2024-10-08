"""Menus and actions for Docker images."""

from __future__ import annotations

from asyncio import iscoroutine
from typing import TYPE_CHECKING, Any, overload

import docker
import docker.errors
from docker_qrcode_page import DockerQRCodePage
from image_ import check_container, find_container
from images_ import IMAGE_IDS, IMAGES
from ubo_gui.menu.types import (
    ActionItem,
    HeadedMenu,
    HeadlessMenu,
    Item,
    SubMenuItem,
)

from ubo_app.constants import DOCKER_CREDENTIALS_TEMPLATE
from ubo_app.logging import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageSetStatusAction,
    DockerState,
    ImageState,
    ImageStatus,
)
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationsAddAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task, to_thread

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence

    from ubo_gui.page import PageWidget

    from ubo_app.store.services.ip import IpNetworkInterface

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


@store.autorun(lambda state: state.docker.service.usernames)
def _reactive_fetch_image(usernames: dict[str, str]) -> Callable[[ImageState], None]:
    def fetch_image(image: ImageState) -> None:
        def act() -> None:
            store.dispatch(
                DockerImageSetStatusAction(
                    image=image.id,
                    status=ImageStatus.FETCHING,
                ),
            )
            try:
                logger.info('Fetching image', extra={'image': IMAGES[image.id].path})
                docker_client = docker.from_env()
                for registry, username in usernames.items():
                    if IMAGES[image.id].registry == registry:
                        docker_client.login(
                            username=username,
                            password=secrets.read_secret(
                                DOCKER_CREDENTIALS_TEMPLATE.format(registry),
                            ),
                            registry=registry,
                        )
                docker_client.images.pull(IMAGES[image.id].path)
                docker_client.close()
            except docker.errors.DockerException:
                logger.exception(
                    'Image error',
                    extra={'image': image.id, 'path': IMAGES[image.id].path},
                )
                store.dispatch(
                    DockerImageSetStatusAction(
                        image=image.id,
                        status=ImageStatus.ERROR,
                    ),
                )

        to_thread(act)

    return fetch_image


def _remove_image(image: ImageState) -> None:
    def act() -> None:
        docker_client = docker.from_env()
        docker_client.images.remove(IMAGES[image.id].path, force=True)
        docker_client.close()

    to_thread(act)


@overload
async def _process_str(
    value: str
    | Callable[[], str | Coroutine[Any, Any, str]]
    | Coroutine[Any, Any, str],
) -> str: ...
@overload
async def _process_str(
    value: str
    | Callable[[], str | Coroutine[Any, Any, str | None] | None]
    | Coroutine[Any, Any, str | None]
    | None,
) -> str | None: ...
async def _process_str(
    value: str
    | Callable[[], str | Coroutine[Any, Any, str | None] | None]
    | Coroutine[Any, Any, str | None]
    | None,
) -> str | None:
    if callable(value):
        value = value()
    if iscoroutine(value):
        value = await value
    return value


async def _process_environment_variables(image_id: str) -> dict[str, str]:
    environment_variables = IMAGES[image_id].environment_vairables or {}
    result: dict[str, str] = {}

    for key in environment_variables:
        result[key] = await _process_str(environment_variables[key])

    return result


@store.autorun(lambda state: state.docker)
def _run_container_generator(docker_state: DockerState) -> Callable[[ImageState], None]:
    def run_container(image: ImageState) -> None:
        async def act() -> None:
            docker_client = docker.from_env()
            container = find_container(docker_client, image=IMAGES[image.id].path)
            if container:
                if container.status != 'running':
                    container.start()
            else:
                hosts = {}
                for key, value in IMAGES[image.id].hosts.items():
                    if not hasattr(docker_state, value):
                        store.dispatch(
                            NotificationsAddAction(
                                notification=Notification(
                                    title='Dependency error',
                                    content=f'Container "{value}" is not loaded',
                                    importance=Importance.MEDIUM,
                                ),
                            ),
                        )
                        return
                    if not getattr(docker_state, value).container_ip:
                        store.dispatch(
                            NotificationsAddAction(
                                notification=Notification(
                                    title='Dependency error',
                                    content=f'Container "{value}" does not have an IP'
                                    ' address',
                                    importance=Importance.MEDIUM,
                                ),
                            ),
                        )
                        return
                    if hasattr(docker_state, value):
                        hosts[key] = getattr(docker_state, value).container_ip
                    else:
                        hosts[key] = value

                docker_client.containers.run(
                    IMAGES[image.id].path,
                    hostname=image.id,
                    publish_all_ports=True,
                    detach=True,
                    volumes=IMAGES[image.id].volumes,
                    ports=IMAGES[image.id].ports,
                    network_mode=IMAGES[image.id].network_mode,
                    environment=await _process_environment_variables(image.id),
                    extra_hosts=hosts,
                    restart_policy={'Name': 'always'},
                    command=await _process_str(IMAGES[image.id].command),
                )
            docker_client.close()

        create_task(act())

    return run_container


def _stop_container(image: ImageState) -> None:
    def act() -> None:
        docker_client = docker.from_env()
        container = find_container(docker_client, image=IMAGES[image.id].path)
        if container and container.status != 'exited':
            container.stop()
        docker_client.close()

    to_thread(act)


def _remove_container(image: ImageState) -> None:
    def act() -> None:
        docker_client = docker.from_env()
        container = find_container(docker_client, image=IMAGES[image.id].path)
        if container:
            container.remove(v=True, force=True)
        docker_client.close()

    to_thread(act)


@store.view(lambda state: state.ip.interfaces)
def image_menu(
    interfaces: Sequence[IpNetworkInterface],
    image: ImageState,
) -> HeadedMenu:
    """Get the menu for the docker image."""
    ip_addresses = [
        ip for interface in interfaces or [] for ip in interface.ip_addresses
    ]
    items: list[Item] = []

    def open_qrcode(port: str) -> Callable[[], PageWidget]:
        def action() -> PageWidget:
            return DockerQRCodePage(ips=ip_addresses, port=port)

        return action

    if image.status == ImageStatus.NOT_AVAILABLE:
        items.append(
            ActionItem(
                label='Fetch',
                icon='󰇚',
                action=lambda: _reactive_fetch_image()(image),
            ),
        )
    elif image.status == ImageStatus.FETCHING:
        pass
    elif image.status == ImageStatus.AVAILABLE:
        items.extend(
            [
                ActionItem(
                    label='Start',
                    icon='󰐊',
                    action=lambda: _run_container_generator()(image),
                ),
                ActionItem(
                    label='Remove image',
                    icon='󰆴',
                    action=lambda: _remove_image(image),
                ),
            ],
        )
    elif image.status == ImageStatus.CREATED:
        items.extend(
            [
                ActionItem(
                    label='Start',
                    icon='󰐊',
                    action=lambda: _run_container_generator()(image),
                ),
                ActionItem(
                    label='Remove container',
                    icon='󰆴',
                    action=lambda: _remove_container(image),
                ),
            ],
        )
    elif image.status == ImageStatus.RUNNING:
        items.append(
            ActionItem(
                label='Stop',
                key='stop',
                icon='󰓛',
                action=lambda: _stop_container(image),
            ),
        )
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

    messages = {
        ImageStatus.NOT_AVAILABLE: 'Image needs to be fetched',
        ImageStatus.FETCHING: 'Image is being fetched',
        ImageStatus.AVAILABLE: 'Image is ready but container is not running',
        ImageStatus.CREATED: 'Container is created but not running',
        ImageStatus.RUNNING: IMAGES[image.id].note or 'Container is running',
        ImageStatus.ERROR: 'Image has an error, please check the logs',
    }

    return HeadedMenu(
        title=f'Docker - {IMAGES[image.id].label}',
        heading=IMAGES[image.id].label,
        sub_heading=messages[image.status],
        items=items,
        placeholder='Waiting...',
    )


def image_menu_generator(image_id: str) -> Callable[[], Callable[[], HeadedMenu]]:
    """Get the menu items for the Docker service."""
    _image_menu = store.autorun(
        lambda state: getattr(state.docker, image_id),
        lambda state: (getattr(state.docker, image_id), state.ip.interfaces),
    )(image_menu)

    def open_image_menu() -> Callable[[], HeadedMenu]:
        check_container(image_id)

        return _image_menu

    return open_image_menu


IMAGE_MENUS = {image_id: image_menu_generator(image_id) for image_id in IMAGE_IDS}
