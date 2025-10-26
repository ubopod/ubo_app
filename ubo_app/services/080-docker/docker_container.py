"""Docker container management."""

from __future__ import annotations

import contextlib
import ipaddress
from asyncio import iscoroutine
from typing import TYPE_CHECKING, Any, overload

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from docker_images import IMAGES
from redux import FinishEvent

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageRemoveContainerEvent,
    DockerImageRunContainerEvent,
    DockerImageSetDockerIdAction,
    DockerImageSetStatusAction,
    DockerImageStopContainerEvent,
    DockerItemStatus,
    DockerState,
)
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import to_thread

# Track which event monitors are already running to prevent duplicates
_active_monitors: set[str] = set()

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


def get_full_image_path(image_id: str) -> str:
    """Get full image path including registry if specified."""
    image_entry = IMAGES[image_id]
    if image_entry.registry:
        return f'{image_entry.registry}/{image_entry.path}'
    return image_entry.path


def find_container(client: docker.DockerClient, *, image: str) -> Container | None:
    """Find a container."""
    for container in client.containers.list(all=True):
        if not isinstance(container, Container):
            continue

        with contextlib.suppress(docker.errors.DockerException):
            container_image = container.image
            if isinstance(container_image, Image):
                # Match with or without registry prefix
                # Handles: docker.io/image:tag ↔ image:tag, ghcr.io/image ↔ image, etc.
                matches = any(
                    tag in image or image in tag
                    for tag in container_image.tags
                )

                if matches:
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
@overload
async def _process_str(
    value: str
    | list[str]
    | Callable[[], str | list[str] | Coroutine[Any, Any, str | list[str]]]
    | Coroutine[Any, Any, str | list[str]],
) -> str | list[str]: ...
@overload
async def _process_str(
    value: str
    | list[str]
    | Callable[[], str | list[str] | Coroutine[Any, Any, str | list[str] | None] | None]
    | Coroutine[Any, Any, str | list[str] | None]
    | None,
) -> str | list[str] | None: ...
async def _process_str(
    value: str
    | list[str]
    | Callable[[], str | list[str] | Coroutine[Any, Any, str | list[str] | None] | None]
    | Coroutine[Any, Any, str | list[str] | None]
    | None,
) -> str | list[str] | None:
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


@store.with_state(lambda state: state.docker)
async def run_container(
    docker_state: DockerState,
    event: DockerImageRunContainerEvent,
) -> None:
    """Run a container."""
    id = event.image

    docker_client = docker.from_env()
    path = get_full_image_path(id)
    container = find_container(docker_client, image=path)
    if container:
        if container.status != 'running':
            container.start()
    else:
        hosts = {}
        # Special Docker host values that should be passed through literally
        special_hosts = {'host-gateway', 'host.docker.internal'}

        for key, value in IMAGES[id].hosts.items():
            # Check if it's a special Docker value or IP address
            is_ip_address = False
            with contextlib.suppress(ValueError):
                ipaddress.ip_address(value)
                is_ip_address = True

            if value in special_hosts or is_ip_address:
                # Pass through special values and IPs directly
                hosts[key] = value
            elif hasattr(docker_state, value):
                # It's a container name - look up its IP
                container_ip = getattr(docker_state, value).container_ip
                if not container_ip:
                    store.dispatch(
                        NotificationsAddAction(
                            notification=Notification(
                                title='Dependency error',
                                content=f'Container "{value}" does not \
                                        have an IP address',
                                importance=Importance.MEDIUM,
                            ),
                        ),
                    )
                    return
                hosts[key] = container_ip
            else:
                # Unknown container - show error
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

        prepare_function = IMAGES[id].prepare
        if prepare_function:
            result = prepare_function()
            if iscoroutine(result):
                result = await result
            if not result:
                logger.error('Failed to prepare the container', extra={'image': id})
                return

        docker_client.containers.run(
            get_full_image_path(id),
            hostname=id,
            publish_all_ports=True,
            detach=True,
            volumes=IMAGES[id].volumes,
            ports=IMAGES[id].ports,
            network_mode=IMAGES[id].network_mode,
            environment=await _process_environment_variables(id),
            extra_hosts=hosts,
            restart_policy={'Name': 'always'},
            command=await _process_str(IMAGES[id].command),
        )
    docker_client.close()


def stop_container(event: DockerImageStopContainerEvent) -> None:
    """Stop a container."""
    id = event.image

    docker_client = docker.from_env()
    container = find_container(docker_client, image=get_full_image_path(id))
    if container and container.status != 'exited':
        container.stop()
    docker_client.close()


def remove_container(event: DockerImageRemoveContainerEvent) -> None:
    """Remove a container."""
    id = event.image

    docker_client = docker.from_env()
    container = find_container(docker_client, image=get_full_image_path(id))
    if container:
        container.remove(v=True, force=True)
    docker_client.close()


def update_container(*, image_id: str, container: Container) -> None:
    """Update a container's state in store based on its real state."""
    if container.status == 'running':
        logger.debug(
            'Container running image found',
            extra={'image': image_id, 'path': get_full_image_path(image_id)},
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
        extra={'image': image_id, 'path': get_full_image_path(image_id)},
    )
    store.dispatch(
        DockerImageSetStatusAction(
            image=image_id,
            status=DockerItemStatus.CREATED,
        ),
    )


def _monitor_events(  # noqa: C901
    image_id: str,
    get_docker_id: Callable[[], str],
) -> None:
    path = get_full_image_path(image_id)
    docker_client = docker.from_env()
    events = docker_client.events(
        decode=True,
        filters={'type': ['image', 'container']},
    )
    store.subscribe_event(
        FinishEvent,
        events.close,
    )
    for event in events:
        logger.verbose('Docker image event', extra={'event': event})
        if event['Type'] == 'image':
            if event['status'] == 'pull' and event['id'] in path:
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
                    raise
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
                else:
                    logger.warning(
                        '_monitor_events: Container not found after start event',
                        extra={'image_id': image_id, 'image_path': path},
                    )
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
    path = get_full_image_path(image_id)

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
            store.dispatch(
                DockerImageSetStatusAction(
                    image=image_id,
                    status=DockerItemStatus.NOT_AVAILABLE,
                ),
            )
            raise
        except docker.errors.DockerException:
            store.dispatch(
                DockerImageSetStatusAction(
                    image=image_id,
                    status=DockerItemStatus.ERROR,
                ),
            )
            raise
        finally:
            docker_client.close()

            # Only start event monitor if not already running for this image
            if image_id not in _active_monitors:
                _active_monitors.add(image_id)
                logger.debug(
                    'Starting event monitor',
                    extra={'image_id': image_id},
                )

                @store.autorun(lambda state: getattr(state.docker, image_id).docker_id)
                def get_docker_id(docker_id: str) -> str:
                    return docker_id

                _monitor_events(image_id, get_docker_id)
            else:
                logger.debug(
                    'Event monitor already running, skipping',
                    extra={'image_id': image_id},
                )

    to_thread(act)
