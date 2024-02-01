"""Setup the service."""
from __future__ import annotations

import asyncio
import contextlib
import subprocess
from dataclasses import fields
from typing import Callable

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from reducer import IMAGE_IDS, IMAGES
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, Item, SubMenuItem

from ubo_app.constants import INSTALLATION_PATH
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


def install_docker() -> None:
    """Install Docker."""
    dispatch(DockerSetStatusAction(status=DockerStatus.INSTALLING))

    # Run the install_docker.sh script
    subprocess.run(
        [f'{INSTALLATION_PATH}/env/bin/ubo', 'install_docker'],  # noqa: S603
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))


def run_docker() -> None:
    """Install Docker."""
    subprocess.run(
        ['/usr/bin/env', 'systemctl', 'start', 'docker'],  # noqa: S603
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

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


def image_menu_generator(image_id: str) -> Callable[[], Callable[[], HeadedMenu]]:
    """Get the menu items for the Docker service."""

    def check_image(path) -> None:
        def act() -> None:
            try:
                logger.debug('Checking image', extra={'image': image_id, 'path': path})
                docker_client = docker.from_env()
                docker_client.images.get(path)
                logger.debug('Image found', extra={'image': image_id, 'path': path})

                for container in docker_client.containers.list(all=True):
                    if (
                        isinstance(container, Container)
                        and isinstance(container.image, Image)
                        and path in container.image.tags
                        and container.status == 'running'
                    ):
                        logger.debug(
                            'Container running image found',
                            extra={'image': image_id, 'path': path},
                        )
                        dispatch(
                            DockerImageSetStatusAction(
                                image=image_id,
                                status=ImageStatus.RUNNING,
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
            except docker.errors.ImageNotFound:
                logger.debug('Image not found', extra={'image': image_id, 'path': path})
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
                    docker_client.images.pull(image.path)
                    logger.debug('Image fetched', extra={'image': image.path})
                    check_image(image.path)
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

            run_in_executor(None, act)

        def run_container() -> None:
            def act() -> None:
                docker_client = docker.from_env()
                for container in docker_client.containers.list(all=True):
                    if (
                        isinstance(container, Container)
                        and isinstance(container.image, Image)
                        and image.path in container.image.tags
                        and container.status != 'running'
                    ):
                        container.start()
                        break
                else:
                    docker_client.containers.run(image.path, detach=True)
                check_image(image.path)

            run_in_executor(None, act)

        def stop_container() -> None:
            def act() -> None:
                docker_client = docker.from_env()
                for container in docker_client.containers.list(all=True):
                    if (
                        isinstance(container, Container)
                        and isinstance(container.image, Image)
                        and image.path in container.image.tags
                        and container.status != 'exited'
                    ):
                        container.stop()
                check_image(image.path)

            run_in_executor(None, act)

        return [
            *(
                [
                    ActionItem(
                        label='Stop',
                        icon='stop',
                        action=stop_container,
                    ),
                ]
                if image.is_running
                else [
                    ActionItem(
                        label='Start',
                        icon='play_arrow',
                        action=run_container,
                    ),
                ]
                if image.is_available
                else []
            ),
            {
                ImageStatus.NOT_AVAILABLE: ActionItem(
                    label='Fetch',
                    icon='download',
                    action=fetch_image,
                ),
                ImageStatus.FETCHING: ActionItem(
                    label='Stop',
                    icon='stop',
                    action=remove_image,
                ),
                ImageStatus.AVAILABLE: ActionItem(
                    label='Remove',
                    icon='delete',
                    action=remove_image,
                ),
                ImageStatus.RUNNING: ActionItem(
                    label='Remove',
                    icon='delete',
                    action=remove_image,
                ),
                ImageStatus.ERROR: ActionItem(
                    label='Check status',
                    icon='refresh',
                    action=lambda: check_image(image.path),
                ),
            }[image.status],
        ]

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


@autorun(lambda state: state.docker.service.status)
def setup_menu(status: DockerStatus) -> HeadedMenu:
    """Get the menu items for the Docker service."""
    if status in [
        DockerStatus.UNKNOWN,
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

            if is_running:
                dispatch(DockerSetStatusAction(status=DockerStatus.RUNNING))
            elif is_installed:
                dispatch(DockerSetStatusAction(status=DockerStatus.NOT_RUNNING))
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
            heading='Installing',
            sub_heading='Docker service is installing',
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


image_menus = {image_id: image_menu_generator(image_id) for image_id in IMAGE_IDS}


@autorun(lambda state: state.docker)
def docker_menu_items(state: DockerState) -> list[Item]:
    """Get the menu items for the Docker service."""
    items: list[Item] = [
        SubMenuItem(
            label='Setup Docker',
            icon='manufacturing',
            sub_menu=setup_menu,
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


docker_main_menu = SubMenuItem(
    label='Docker',
    icon='D',
    sub_menu=HeadlessMenu(
        title='Docker',
        items=docker_menu_items,
    ),
)


def init_service() -> None:
    """Initialize the service."""
    dispatch(RegisterSettingAppAction(menu_item=docker_main_menu))
