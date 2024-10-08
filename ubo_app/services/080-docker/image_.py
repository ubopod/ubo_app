"""Docker image menu."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from images_ import IMAGES
from redux import FinishEvent

from ubo_app.logging import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageSetDockerIdAction,
    DockerImageSetStatusAction,
    ImageStatus,
)
from ubo_app.utils.async_ import to_thread

if TYPE_CHECKING:
    from collections.abc import Callable


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
        store.dispatch(
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
    store.dispatch(
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
    store.subscribe_event(FinishEvent, events.close)
    for event in events:
        logger.verbose('Docker image event', extra={'event': event})
        if event['Type'] == 'image':
            if event['status'] == 'pull' and event['id'] == path:
                try:
                    image = docker_client.images.get(path)
                    store.dispatch(
                        DockerImageSetStatusAction(
                            image=image_id,
                            status=ImageStatus.AVAILABLE,
                        ),
                    )
                    if isinstance(image, Image) and image.id:
                        store.dispatch(
                            DockerImageSetDockerIdAction(
                                image=image_id,
                                docker_id=image.id,
                            ),
                        )
                except docker.errors.DockerException:
                    store.dispatch(
                        DockerImageSetStatusAction(
                            image=image_id,
                            status=ImageStatus.NOT_AVAILABLE,
                        ),
                    )
            elif event['status'] == 'delete' and event['id'] == get_docker_id():
                store.dispatch(
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
                store.dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=ImageStatus.CREATED,
                    ),
                )
            elif event['status'] == 'destroy' and event['from'] == path:
                store.dispatch(
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
                store.dispatch(
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
            store.dispatch(
                DockerImageSetStatusAction(
                    image=image_id,
                    status=ImageStatus.AVAILABLE,
                ),
            )
        except docker.errors.ImageNotFound:
            logger.debug(
                'Image not found',
                extra={'image': image_id, 'path': path},
                exc_info=True,
            )
            store.dispatch(
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
            store.dispatch(
                DockerImageSetStatusAction(
                    image=image_id,
                    status=ImageStatus.ERROR,
                ),
            )
        finally:
            docker_client.close()

            @store.autorun(lambda state: getattr(state.docker, image_id).docker_id)
            def get_docker_id(docker_id: str) -> str:
                return docker_id

            _monitor_events(image_id, get_docker_id)

    to_thread(act)
