"""Docker container management."""

from __future__ import annotations

import contextlib
from asyncio import iscoroutine
from typing import TYPE_CHECKING, Any, overload

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from docker_images import IMAGES
from redux import AutorunOptions, FinishEvent

from ubo_app.logging import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageSetDockerIdAction,
    DockerImageSetStatusAction,
    DockerItemStatus,
    DockerState,
    ImageState,
)
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import to_thread

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


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


def run_container(*, image: ImageState) -> None:
    """Run a container."""

    @store.autorun(
        lambda state: state.docker,
        options=AutorunOptions(keep_ref=False),
    )
    async def _(docker_state: DockerState) -> None:
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


def stop_container(*, image: ImageState) -> None:
    """Stop a container."""

    def act() -> None:
        docker_client = docker.from_env()
        container = find_container(docker_client, image=IMAGES[image.id].path)
        if container and container.status != 'exited':
            container.stop()
        docker_client.close()

    to_thread(act)


def remove_container(*, image: ImageState) -> None:
    """Remove a container."""

    def act() -> None:
        docker_client = docker.from_env()
        container = find_container(docker_client, image=IMAGES[image.id].path)
        if container:
            container.remove(v=True, force=True)
        docker_client.close()

    to_thread(act)


def update_container(*, image_id: str, container: Container) -> None:
    """Update a container's state in store based on its real state."""
    if container.status == 'running':
        logger.debug(
            'Container running image found',
            extra={'image': image_id, 'path': IMAGES[image_id].path},
        )
        store.dispatch(
            DockerImageSetStatusAction(
                image=image_id,
                status=DockerItemStatus.RUNNING,
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
            status=DockerItemStatus.CREATED,
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
                            status=DockerItemStatus.AVAILABLE,
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
                            status=DockerItemStatus.NOT_AVAILABLE,
                        ),
                    )
            elif event['status'] == 'delete' and event['id'] == get_docker_id():
                store.dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=DockerItemStatus.NOT_AVAILABLE,
                    ),
                )
        elif event['Type'] == 'container':
            if (
                event['status'] in 'start'
                or event['status'].startswith('exec_create')
                or event['status'].startswith('exec_start')
            ) and event['from'] == path:
                container = find_container(docker_client, image=path)
                if container:
                    update_container(image_id=image_id, container=container)
            elif event['status'] == 'die' and event['from'] == path:
                store.dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=DockerItemStatus.CREATED,
                    ),
                )
            elif event['status'] == 'destroy' and event['from'] == path:
                store.dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=DockerItemStatus.AVAILABLE,
                    ),
                )


def check_container(*, image_id: str) -> None:
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
                update_container(image_id=image_id, container=container)
                return

            logger.debug(
                'Container running image not found',
                extra={'image': image_id, 'path': path},
            )
            store.dispatch(
                DockerImageSetStatusAction(
                    image=image_id,
                    status=DockerItemStatus.AVAILABLE,
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
                    status=DockerItemStatus.NOT_AVAILABLE,
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
                    status=DockerItemStatus.ERROR,
                ),
            )
        finally:
            docker_client.close()

            @store.autorun(lambda state: getattr(state.docker, image_id).docker_id)
            def get_docker_id(docker_id: str) -> str:
                return docker_id

            _monitor_events(image_id, get_docker_id)

    to_thread(act)
