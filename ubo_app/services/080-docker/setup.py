"""Setup the service."""
from __future__ import annotations

import asyncio
import contextlib
import socket
import subprocess
from dataclasses import fields
from pathlib import Path
from typing import Callable

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from reducer import IMAGE_IDS, IMAGES
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, Item, SubMenuItem

from ubo_app.constants import DOCKER_INSTALLATION_LOCK_FILE, SOCKET_PATH
from ubo_app.logging import logger
from ubo_app.store import autorun, dispatch
from ubo_app.store.main import RegisterSettingAppAction
from ubo_app.store.services.docker import (
    DockerImageSetStatusAction,
    DockerSetStatusAction,
    DockerState,
    DockerStatus,
    ImageState,
    ImageStatus,
)
from ubo_app.utils.async_ import create_task, run_in_executor


def send_command(command: bytes) -> None:
    """Send a command to the system manager socket."""
    server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        server_socket.connect(SOCKET_PATH)
    except Exception as exception:  # noqa: BLE001
        logger.error('Unable to connect to the socket', exc_info=exception)
        return
    else:
        server_socket.send(command)
    finally:
        server_socket.close()


def install_docker() -> None:
    """Install Docker."""
    dispatch(DockerSetStatusAction(status=DockerStatus.INSTALLING))

    if Path(SOCKET_PATH).exists():
        send_command(b'docker install')


def run_docker() -> None:
    """Install Docker."""
    send_command(b'docker start')

    dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))


def stop_docker() -> None:
    """Install Docker."""
    subprocess.run(
        ['/usr/bin/env', 'systemctl', 'stop', 'docker'],  # noqa: S603
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))


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


@autorun(lambda state: state.docker.service.status)
def setup_menu(status: DockerStatus) -> HeadedMenu:
    """Get the menu items for the Docker service."""
    if status in [
        DockerStatus.UNKNOWN,
        DockerStatus.INSTALLING,
        DockerStatus.NOT_INSTALLED,
        DockerStatus.NOT_RUNNING,
    ]:

        async def check_docker() -> None:
            """Check if Docker is installed."""
            process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'which',
                'docker',
            )
            await process.wait()
            is_installed = process.returncode == 0

            is_running = False
            with contextlib.suppress(docker.errors.DockerException):
                docker_client = docker.from_env()
                is_running = docker_client.ping()
                docker_client.close()

            if is_running:
                dispatch(DockerSetStatusAction(status=DockerStatus.RUNNING))
            elif is_installed:
                dispatch(DockerSetStatusAction(status=DockerStatus.NOT_RUNNING))
            elif Path(DOCKER_INSTALLATION_LOCK_FILE).exists():
                dispatch(DockerSetStatusAction(status=DockerStatus.INSTALLING))
            else:
                dispatch(DockerSetStatusAction(status=DockerStatus.NOT_INSTALLED))

        create_task(check_docker())

    title = 'Setup Docker'
    if status == DockerStatus.UNKNOWN:
        return HeadedMenu(
            title=title,
            heading='Checking',
            sub_heading='Checking Docker service status',
            items=[],
        )
    if status == DockerStatus.NOT_INSTALLED:
        return HeadedMenu(
            title=title,
            heading='Docker is not Installed',
            sub_heading='Install it to enjoy the power of Docker on your Ubo pod',
            items=[
                ActionItem(
                    label='Install Docker',
                    icon='system_update',
                    action=install_docker,
                ),
            ],
        )
    if status == DockerStatus.INSTALLING:
        return HeadedMenu(
            title=title,
            heading='Installing...',
            sub_heading='Docker is being installed',
            items=[],
        )
    if status == DockerStatus.NOT_RUNNING:
        return HeadedMenu(
            title=title,
            heading='Docker is not Running',
            sub_heading='Run it to enjoy the power of Docker on your Ubo pod',
            items=[
                ActionItem(
                    label='Start Docker',
                    icon='play_arrow',
                    action=run_docker,
                ),
            ],
        )
    if status == DockerStatus.RUNNING:
        return HeadedMenu(
            title=title,
            heading='Docker is Running',
            sub_heading='Enjoy the power of Docker on your Ubo pod',
            items=[
                ActionItem(
                    label='Stop Docker',
                    icon='stop',
                    action=stop_docker,
                ),
            ],
        )
    if status == DockerStatus.ERROR:
        return HeadedMenu(
            title=title,
            heading='Docker Error',
            sub_heading='Please check the logs for more information',
            items=[],
        )

    msg = f'Unknown status: {status}'
    raise ValueError(msg)


def image_menu_generator(image_id: str) -> Callable[[], Callable[[], HeadedMenu]]:
    """Get the menu items for the Docker service."""

    def check_image(path: str) -> None:
        def act() -> None:
            logger.debug('Checking image', extra={'image': image_id, 'path': path})
            docker_client = docker.from_env()
            try:
                docker_client.images.get(path)
                logger.debug('Image found', extra={'image': image_id, 'path': path})

                container = find_container(docker_client, image=path)
                if container:
                    if container.status == 'running':
                        logger.debug(
                            'Container running image found',
                            extra={'image': image_id, 'path': path},
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
                            ),
                        )
                        return
                    logger.debug(
                        "Container for the image found, but it's not running",
                        extra={'image': image_id, 'path': path},
                    )
                    dispatch(
                        DockerImageSetStatusAction(
                            image=image_id,
                            status=ImageStatus.CREATED,
                        ),
                    )
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
            except docker.errors.ImageNotFound as exception:
                logger.debug(
                    'Image not found',
                    extra={'image': image_id, 'path': path},
                    exc_info=exception,
                )
                dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=ImageStatus.NOT_AVAILABLE,
                    ),
                )
            except docker.errors.DockerException as exception:
                logger.debug(
                    'Image error',
                    extra={'image': image_id, 'path': path},
                    exc_info=exception,
                )
                dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=ImageStatus.ERROR,
                    ),
                )
            finally:
                docker_client.close()

        run_in_executor(None, act)

    @autorun(lambda state: getattr(state.docker, image_id))
    def image_items(image: ImageState) -> list[Item]:
        def fetch_image() -> None:
            def act() -> None:
                dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=ImageStatus.FETCHING,
                    ),
                )
                try:
                    logger.debug('Fetching image', extra={'image': image.path})
                    docker_client = docker.from_env()
                    response = docker_client.api.pull(
                        image.path,
                        stream=True,
                        decode=True,
                    )
                    for line in response:
                        logger.verbose(
                            'Image pull',
                            extra={'image': image.path, 'line': line},
                        )
                    logger.debug('Image fetched', extra={'image': image.path})
                    check_image(image.path)
                    docker_client.close()
                except docker.errors.DockerException as exception:
                    logger.debug(
                        'Image error',
                        extra={'image': image.path},
                        exc_info=exception,
                    )
                    dispatch(
                        DockerImageSetStatusAction(
                            image=image_id,
                            status=ImageStatus.ERROR,
                        ),
                    )

            run_in_executor(None, act)

        def remove_image() -> None:
            def act() -> None:
                docker_client = docker.from_env()
                docker_client.images.remove(image.path, force=True)
                check_image(image.path)
                docker_client.close()

            run_in_executor(None, act)

        def run_container() -> None:
            def act() -> None:
                docker_client = docker.from_env()
                container = find_container(docker_client, image=image.path)
                if container:
                    if container.status != 'running':
                        container.start()
                else:
                    docker_client.containers.run(
                        image.path,
                        publish_all_ports=True,
                        detach=True,
                        volumes=IMAGES[image_id].volumes,
                        **(
                            {'ports': IMAGES[image_id].ports}
                            if IMAGES[image_id].ports
                            else {}
                        ),
                    )
                check_image(image.path)
                docker_client.close()

            run_in_executor(None, act)

        def stop_container() -> None:
            def act() -> None:
                docker_client = docker.from_env()
                container = find_container(docker_client, image=image.path)
                if container and container.status != 'exited':
                    container.stop()
                check_image(image.path)
                docker_client.close()

            run_in_executor(None, act)

        def remove_container() -> None:
            def act() -> None:
                docker_client = docker.from_env()
                container = find_container(docker_client, image=image.path)
                if container:
                    container.remove(v=True, force=True)
                check_image(image.path)
                docker_client.close()

            run_in_executor(None, act)

        items: list[Item] = []

        if image.status == ImageStatus.NOT_AVAILABLE:
            items.append(
                ActionItem(
                    label='Fetch',
                    icon='download',
                    action=fetch_image,
                ),
            )
        elif image.status == ImageStatus.FETCHING:
            items.append(
                ActionItem(
                    label='Stop',
                    icon='stop',
                    action=remove_image,
                ),
            )
        elif image.status == ImageStatus.AVAILABLE:
            items.extend(
                [
                    ActionItem(
                        label='Start',
                        icon='play_arrow',
                        action=run_container,
                    ),
                    ActionItem(
                        label='Remove image',
                        icon='delete',
                        action=remove_image,
                    ),
                ],
            )
        elif image.status == ImageStatus.CREATED:
            items.extend(
                [
                    ActionItem(
                        label='Start',
                        icon='play_arrow',
                        action=run_container,
                    ),
                    ActionItem(
                        label='Remove container',
                        icon='delete',
                        action=remove_container,
                    ),
                ],
            )
        elif image.status == ImageStatus.RUNNING:
            items.append(
                ActionItem(
                    label='Stop',
                    icon='stop',
                    action=stop_container,
                ),
            )
            items.append(
                SubMenuItem(
                    label='ports',
                    icon='category',
                    sub_menu=HeadlessMenu(
                        title='Ports',
                        items=[Item(label=i, icon='category') for i in image.ports],
                    ),
                ),
            )
        elif image.status == ImageStatus.ERROR:
            items.append(
                ActionItem(
                    label='Check status',
                    icon='refresh',
                    action=lambda: check_image(image.path),
                ),
            )

        return items

    @autorun(lambda state: getattr(state.docker, image_id))
    def image_menu(
        image: ImageState,
    ) -> HeadedMenu:
        """Get the menu items for the Docker service."""
        return HeadedMenu(
            title=f'Docker - {image.label}',
            heading=image.label,
            sub_heading={
                ImageStatus.NOT_AVAILABLE: 'Image needs to be fetched',
                ImageStatus.FETCHING: 'Image is being fetched',
                ImageStatus.AVAILABLE: 'Image is ready but container is not running',
                ImageStatus.CREATED: 'Container is created but not running',
                ImageStatus.RUNNING: 'Container is running',
                ImageStatus.ERROR: 'Image has an error, please check the logs',
            }[image.status],
            items=image_items,
        )

    def image_action() -> Callable[[], HeadedMenu]:
        """Get the menu items for the Docker service."""
        check_image(IMAGES[image_id].path)

        return image_menu

    return image_action


image_menus = {image_id: image_menu_generator(image_id) for image_id in IMAGE_IDS}


def setup_menu_action() -> Callable[[], HeadedMenu]:
    """Get the menu items for the Docker service."""
    dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))
    return setup_menu


@autorun(lambda state: state.docker)
def docker_menu_items(state: DockerState) -> list[Item]:
    """Get the menu items for the Docker service."""
    items: list[Item] = [
        ActionItem(
            label='Setup Docker',
            icon='manufacturing',
            action=setup_menu_action,
        ),
    ]

    if state.service.status == DockerStatus.RUNNING:
        items.append(
            SubMenuItem(
                label='Docker Containers',
                icon='category',
                sub_menu=HeadlessMenu(
                    title='Docker Containers',
                    items=[
                        ActionItem(
                            label=getattr(state, image_id).label,
                            icon=getattr(state, image_id).icon,
                            action=image_menus[image_id],
                        )
                        for image_id in (field.name for field in fields(state))
                        if image_id not in (field.name for field in fields(DockerState))
                    ],
                ),
            ),
        )

    return items


def docker_menu_item_action() -> HeadlessMenu:
    """Get the menu items for the Docker service."""
    return HeadlessMenu(
        title='Docker',
        items=docker_menu_items,
    )


docker_main_menu = ActionItem(
    label='Docker',
    icon='D',
    action=docker_menu_item_action,
)


def init_service() -> None:
    """Initialize the service."""
    dispatch(RegisterSettingAppAction(menu_item=docker_main_menu))
