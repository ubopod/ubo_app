"""Docker image menu."""
from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Callable

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from reducer import IMAGE_IDS, IMAGES
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, Item, SubMenuItem

from ubo_app.logging import logger
from ubo_app.store import autorun, dispatch
from ubo_app.store.services.docker import (
    DockerImageSetDockerIdAction,
    DockerImageSetStatusAction,
    ImageState,
    ImageStatus,
)
from ubo_app.utils.async_ import run_in_executor

if TYPE_CHECKING:
    from asyncio import Future


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


def _monitor_events(
    image_id: str,
    get_docker_id: Callable[[], str],
    docker_client: docker.DockerClient,
) -> None:
    path = IMAGES[image_id].path
    events = docker_client.events(
        decode=True,
        filters={'type': ['image', 'container']},
    )
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
                dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=ImageStatus.RUNNING,
                    ),
                )
            elif event['status'] == 'die' and event['from'] == path:
                dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=ImageStatus.CREATED,
                    ),
                )


def check_container(image_id: str) -> Future[None]:
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

            @autorun(lambda state: getattr(state.docker, image_id).docker_id)
            def get_docker_id(docker_id: str) -> str:
                return docker_id

            _monitor_events(image_id, get_docker_id, docker_client)
            docker_client.close()

    return run_in_executor(None, act)


def _fetch_image(image: ImageState) -> None:
    def act() -> None:
        dispatch(
            DockerImageSetStatusAction(
                image=image.id,
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
                dispatch(
                    DockerImageSetStatusAction(
                        image=image.id,
                        status=ImageStatus.FETCHING,
                    ),
                )
                logger.verbose(
                    'Image pull',
                    extra={'image': image.path, 'line': line},
                )
            logger.debug('Image fetched', extra={'image': image.path})
            docker_client.close()
        except docker.errors.DockerException as exception:
            logger.debug(
                'Image error',
                extra={'image': image.path},
                exc_info=exception,
            )
            dispatch(
                DockerImageSetStatusAction(
                    image=image.id,
                    status=ImageStatus.ERROR,
                ),
            )

    run_in_executor(None, act)


def _remove_image(image: ImageState) -> None:
    def act() -> None:
        docker_client = docker.from_env()
        docker_client.images.remove(image.path, force=True)
        docker_client.close()

    run_in_executor(None, act)


def _run_container(image: ImageState) -> None:
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
                volumes=IMAGES[image.id].volumes,
                ports=IMAGES[image.id].ports,
            )
        docker_client.close()

    run_in_executor(None, act)


def _stop_container(image: ImageState) -> None:
    def act() -> None:
        docker_client = docker.from_env()
        container = find_container(docker_client, image=image.path)
        if container and container.status != 'exited':
            container.stop()
        docker_client.close()

    run_in_executor(None, act)


def _remove_container(image: ImageState) -> None:
    def act() -> None:
        docker_client = docker.from_env()
        container = find_container(docker_client, image=image.path)
        if container:
            container.remove(v=True, force=True)
        docker_client.close()

    run_in_executor(None, act)


def image_menu_generator(image_id: str) -> Callable[[], Callable[[], HeadedMenu]]:
    """Get the menu items for the Docker service."""

    @autorun(lambda state: getattr(state.docker, image_id))
    def image_menu(
        image: ImageState,
    ) -> HeadedMenu:
        """Get the menu for the docker image."""
        items: list[Item] = []

        if image.status == ImageStatus.NOT_AVAILABLE:
            items.append(
                ActionItem(
                    label='Fetch',
                    icon='download',
                    action=lambda: _fetch_image(image),
                ),
            )
        elif image.status == ImageStatus.FETCHING:
            items.append(
                ActionItem(
                    label='Stop',
                    icon='stop',
                    action=lambda: _remove_image(image),
                ),
            )
        elif image.status == ImageStatus.AVAILABLE:
            items.extend(
                [
                    ActionItem(
                        label='Start',
                        icon='play_arrow',
                        action=lambda: _run_container(image),
                    ),
                    ActionItem(
                        label='Remove image',
                        icon='delete',
                        action=lambda: _remove_image(image),
                    ),
                ],
            )
        elif image.status == ImageStatus.CREATED:
            items.extend(
                [
                    ActionItem(
                        label='Start',
                        icon='play_arrow',
                        action=lambda: _run_container(image),
                    ),
                    ActionItem(
                        label='Remove container',
                        icon='delete',
                        action=lambda: _remove_container(image),
                    ),
                ],
            )
        elif image.status == ImageStatus.RUNNING:
            items.append(
                ActionItem(
                    label='Stop',
                    icon='stop',
                    action=lambda: _stop_container(image),
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
            items=items,
        )

    def image_action() -> Callable[[], HeadedMenu]:
        """Get the menu items for the Docker service."""
        check_container(image_id)

        return image_menu

    return image_action


image_menus = {image_id: image_menu_generator(image_id) for image_id in IMAGE_IDS}
