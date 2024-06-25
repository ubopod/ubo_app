"""Docker image menu."""

from __future__ import annotations

import contextlib
import pathlib
from asyncio import iscoroutine
from typing import TYPE_CHECKING, Any, cast, overload

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from kivy.lang.builder import Builder
from kivy.properties import ListProperty, NumericProperty, StringProperty
from reducer import IMAGE_IDS, IMAGES
from redux import FinishEvent
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, Item, SubMenuItem
from ubo_gui.page import PageWidget

from ubo_app.constants import DOCKER_CREDENTIALS_TEMPLATE
from ubo_app.logging import logger
from ubo_app.store.main import autorun, dispatch, subscribe_event, view
from ubo_app.store.services.docker import (
    DockerImageSetDockerIdAction,
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
    from collections.abc import Callable, Coroutine, Mapping, Sequence

    from ubo_app.store.services.ip import IpNetworkInterface


def find_container(client: docker.DockerClient, *, image: str) -> Container | None:
    """Find a container."""
    for container in client.containers.list(all=True):
        if not isinstance(container, Container):
            continue

        with contextlib.suppress(docker.errors.DockerException):
            container_image = container.image
            if isinstance(container_image, Image) and image in container_image.tags:
                return container
    return None


def update_container(image_id: str, container: Container) -> None:
    """Update a container's state in store based on its real state."""
    if container.status == 'running':
        logger.debug(
            'Container running image found',
            extra={'image': image_id, 'path': IMAGES[image_id].path},
        )
        dispatch(
            DockerImageSetStatusAction(
                image=image_id,
                status=ImageStatus.RUNNING,
                ports=[
                    f'{i["HostIp"]}:{i["HostPort"]}'
                    for i in container.ports.values()
                    for i in i
                ],
                ip=container.attrs['NetworkSettings']['Networks']['bridge']['IPAddress']
                if container.attrs
                and 'bridge' in container.attrs['NetworkSettings']['Networks']
                else None,
            ),
        )
        return
    logger.debug(
        "Container for the image found, but it's not running",
        extra={'image': image_id, 'path': IMAGES[image_id].path},
    )
    dispatch(
        DockerImageSetStatusAction(
            image=image_id,
            status=ImageStatus.CREATED,
        ),
    )


def _monitor_events(image_id: str, get_docker_id: Callable[[], str]) -> None:  # noqa: C901
    path = IMAGES[image_id].path
    docker_client = docker.from_env()
    events = docker_client.events(
        decode=True,
        filters={'type': ['image', 'container']},
    )
    subscribe_event(FinishEvent, events.close)
    for event in events:
        logger.verbose('Docker image event', extra={'event': event})
        if event['Type'] == 'image':
            if event['status'] == 'pull' and event['id'] == path:
                try:
                    image = docker_client.images.get(path)
                    dispatch(
                        DockerImageSetStatusAction(
                            image=image_id,
                            status=ImageStatus.AVAILABLE,
                        ),
                    )
                    if isinstance(image, Image) and image.id:
                        dispatch(
                            DockerImageSetDockerIdAction(
                                image=image_id,
                                docker_id=image.id,
                            ),
                        )
                except docker.errors.DockerException:
                    dispatch(
                        DockerImageSetStatusAction(
                            image=image_id,
                            status=ImageStatus.NOT_AVAILABLE,
                        ),
                    )
            elif event['status'] == 'delete' and event['id'] == get_docker_id():
                dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=ImageStatus.NOT_AVAILABLE,
                    ),
                )
        elif event['Type'] == 'container':
            if event['status'] == 'start' and event['from'] == path:
                container = find_container(docker_client, image=path)
                if container:
                    update_container(image_id, container)
            elif event['status'] == 'die' and event['from'] == path:
                dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=ImageStatus.CREATED,
                    ),
                )
            elif event['status'] == 'destroy' and event['from'] == path:
                dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=ImageStatus.AVAILABLE,
                    ),
                )


def check_container(image_id: str) -> None:
    """Check the container status."""
    path = IMAGES[image_id].path

    def act() -> None:
        logger.debug('Checking image', extra={'image': image_id, 'path': path})
        docker_client = docker.from_env()
        try:
            image = docker_client.images.get(path)
            if not isinstance(image, Image):
                raise docker.errors.ImageNotFound(path)  # noqa: TRY301

            if image.id:
                dispatch(
                    DockerImageSetDockerIdAction(
                        image=image_id,
                        docker_id=image.id,
                    ),
                )
            logger.debug('Image found', extra={'image': image_id, 'path': path})

            container = find_container(docker_client, image=path)
            if container:
                update_container(image_id, container)
                return

            logger.debug(
                'Container running image not found',
                extra={'image': image_id, 'path': path},
            )
            dispatch(
                DockerImageSetStatusAction(
                    image=image_id,
                    status=ImageStatus.AVAILABLE,
                ),
            )
        except docker.errors.ImageNotFound:
            logger.exception(
                'Image not found',
                extra={'image': image_id, 'path': path},
            )
            dispatch(
                DockerImageSetStatusAction(
                    image=image_id,
                    status=ImageStatus.NOT_AVAILABLE,
                ),
            )
        except docker.errors.DockerException:
            logger.exception(
                'Image error',
                extra={'image': image_id, 'path': path},
            )
            dispatch(
                DockerImageSetStatusAction(
                    image=image_id,
                    status=ImageStatus.ERROR,
                ),
            )
        finally:
            docker_client.close()

            @autorun(lambda state: getattr(state.docker, image_id).docker_id)
            def get_docker_id(docker_id: str) -> str:
                return docker_id

            _monitor_events(image_id, get_docker_id)

    to_thread(act)


@autorun(lambda state: state.docker.service.usernames)
def _reactive_fetch_image(usernames: dict[str, str]) -> Callable[[ImageState], None]:
    def fetch_image(image: ImageState) -> None:
        def act() -> None:
            dispatch(
                DockerImageSetStatusAction(
                    image=image.id,
                    status=ImageStatus.FETCHING,
                ),
            )
            try:
                logger.debug('Fetching image', extra={'image': IMAGES[image.id].path})
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
                    extra={'image': IMAGES[image.id].path},
                )
                dispatch(
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
        value = cast(str, await value)
    return value


async def _process_environment_variables(image_id: str) -> Mapping[str, str | None]:
    environment_variables = IMAGES[image_id].environment_vairables or {}
    result: dict[str, str | None] = {}

    for key in environment_variables:
        result[key] = await _process_str(environment_variables[key])

    return result


@autorun(lambda state: state.docker)
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
                        dispatch(
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
                        dispatch(
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


class DockerQRCodePage(PageWidget):
    """QR code for the container's url (ip and port)."""

    ips: list[str] = ListProperty()
    port: str = StringProperty()
    index: int = NumericProperty(0)

    def go_down(self: DockerQRCodePage) -> None:
        """Go down."""
        self.index = (self.index + 1) % len(self.ips)
        self.ids.slider.animated_value = len(self.ips) - 1 - self.index

    def go_up(self: DockerQRCodePage) -> None:
        """Go up."""
        self.index = (self.index - 1) % len(self.ips)
        self.ids.slider.animated_value = len(self.ips) - 1 - self.index


@view(lambda state: state.ip.interfaces)
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
                icon='󰓛',
                action=lambda: _stop_container(image),
            ),
        )
        items.append(
            SubMenuItem(
                label='Ports',
                icon='󰙜',
                sub_menu=HeadlessMenu(
                    title='Ports',
                    items=[
                        ActionItem(
                            label=port,
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

    return HeadedMenu(
        title=f'Docker - {IMAGES[image.id].label}',
        heading=IMAGES[image.id].label,
        sub_heading={
            ImageStatus.NOT_AVAILABLE: 'Image needs to be fetched',
            ImageStatus.FETCHING: 'Image is being fetched',
            ImageStatus.AVAILABLE: 'Image is ready but container is not running',
            ImageStatus.CREATED: 'Container is created but not running',
            ImageStatus.RUNNING: IMAGES[image.id].note or 'Container is running',
            ImageStatus.ERROR: 'Image has an error, please check the logs',
        }[image.status],
        items=items,
        placeholder='Waiting...',
    )


def image_menu_generator(image_id: str) -> Callable[[], Callable[[], HeadedMenu]]:
    """Get the menu items for the Docker service."""
    _image_menu = autorun(lambda state: getattr(state.docker, image_id))(image_menu)

    def open_image_menu() -> Callable[[], HeadedMenu]:
        check_container(image_id)

        return _image_menu

    return open_image_menu


IMAGE_MENUS = {image_id: image_menu_generator(image_id) for image_id in IMAGE_IDS}
Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('docker_qrcode_page.kv')
    .resolve()
    .as_posix(),
)
