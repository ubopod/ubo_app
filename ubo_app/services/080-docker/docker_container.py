"""Docker container management."""

from __future__ import annotations

import contextlib
import ipaddress
import threading
from inspect import isawaitable
from typing import TYPE_CHECKING, overload

import docker
import docker.errors
from apps import IMAGES
from docker.models.containers import Container
from docker.models.images import Image
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


def _start_event_monitor(image_id: str, get_docker_id: Callable[[], str]) -> None:
    """Run the long-lived docker event monitor outside the shared thread pool."""
    thread = threading.Thread(
        target=_monitor_events,
        kwargs={
            'image_id': image_id,
            'get_docker_id': get_docker_id,
        },
        name=f'docker-monitor:{image_id}',
        daemon=True,
    )
    thread.start()

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def find_container(client: docker.DockerClient, *, image_path: str) -> Container | None:
    """Find a container by image path (without registry).

    Args:
        client: Docker client instance.
        image_path: Image path without registry (e.g., 'homebridge/homebridge:latest').

    """
    for container in client.containers.list(all=True):
        if not isinstance(container, Container):
            continue

        with contextlib.suppress(docker.errors.DockerException):
            container_image = container.image
            if isinstance(container_image, Image):
                # Check if any tag matches exactly or ends with the image path
                # (to handle registry prefixes like docker.io/path or ghcr.io/path)
                for tag in container_image.tags:
                    if tag == image_path or tag.endswith(f'/{image_path}'):
                        return container

    return None


@overload
async def _process_str(
    value: str
    | Callable[[], str | Awaitable[str]]
    | Awaitable[str],
) -> str: ...
@overload
async def _process_str(
    value: str
    | Callable[[], str | Awaitable[str | None] | None]
    | Awaitable[str | None]
    | None,
) -> str | None: ...
@overload
async def _process_str(
    value: str
    | list[str]
    | Callable[[], str | list[str] | Awaitable[str | list[str]]]
    | Awaitable[str | list[str]],
) -> str | list[str]: ...
@overload
async def _process_str(
    value: str
    | list[str]
    | Callable[[], str | list[str] | Awaitable[str | list[str] | None] | None]
    | Awaitable[str | list[str] | None]
    | None,
) -> str | list[str] | None: ...
async def _process_str(
    value: str
    | list[str]
    | Callable[[], str | list[str] | Awaitable[str | list[str] | None] | None]
    | Awaitable[str | list[str] | None]
    | None,
) -> str | list[str] | None:
    if callable(value):
        value = value()
    if isawaitable(value):
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
    from docker_app import prepare_app

    id = event.image

    docker_client = docker.from_env()
    container = find_container(docker_client, image_path=IMAGES[id].path)
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

        # Prepare the container (if needed)
        if not await prepare_app(IMAGES[id]):
            docker_client.close()
            return

        docker_client.containers.run(
            IMAGES[id].full_path,
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
    container = find_container(docker_client, image_path=IMAGES[id].path)
    if container and container.status != 'exited':
        container.stop()
    docker_client.close()


def remove_container(event: DockerImageRemoveContainerEvent) -> None:
    """Remove a container."""
    id = event.image

    docker_client = docker.from_env()
    container = find_container(docker_client, image_path=IMAGES[id].path)
    if container:
        container.remove(v=True, force=True)
    docker_client.close()


def update_container(*, image_id: str, container: Container) -> None:
    """Update a container's state in store based on its real state."""
    if container.status == 'running':
        logger.debug(
            'Container running image found',
            extra={'image': image_id, 'path': IMAGES[image_id].full_path},
        )
        store.dispatch(
            DockerImageSetStatusAction(
                image=image_id,
                status=DockerItemStatus.STARTING,
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
        extra={'image': image_id, 'path': IMAGES[image_id].full_path},
    )
    store.dispatch(
        DockerImageSetStatusAction(
            image=image_id,
            status=DockerItemStatus.CREATED,
        ),
    )


def _monitor_events(  # noqa: C901, PLR0912
    image_id: str,
    get_docker_id: Callable[[], str],
) -> None:
    path = IMAGES[image_id].full_path
    logger.info(
        'Starting event monitor',
        extra={'image_id': image_id, 'path': path},
    )
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
        logger.verbose('Docker event received',
        extra={
            'event': event,
            'image_id': image_id,
        })
        if event.get('Type') == 'image':
            # Docker image events use 'Action' key, not 'status'
            action = event.get('Action') or event.get('status')
            logger.debug(
                'Image event received',
                extra={
                    'image_id': image_id,
                    'action': action,
                    'event_id': event.get('id'),
                    'docker_id': get_docker_id(),
                    'path': path,
                },
            )
            if action == 'pull' and str(event.get('id', '')) in path:
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
            elif action == 'delete':
                # For delete events, event.get('id') is often None
                # Check if we have a docker_id tracked
                # (meaning we're monitoring this image)
                current_docker_id = get_docker_id()
                if current_docker_id:
                    store.dispatch(
                        DockerImageSetStatusAction(
                            image=image_id,
                            status=DockerItemStatus.NOT_AVAILABLE,
                        ),
                    )
        elif event.get('Type') == 'container':
            # Container events use 'Action' key (like 'start', 'die', 'destroy')
            # but some older events might use 'status'
            status = event.get('Action') or event.get('status')
            # Get the image path from Actor.Attributes.image or 'from' field
            event_image = event.get('from') or (
                event.get('Actor', {}).get('Attributes', {}).get('image')
            )
            if status is None:
                logger.warning(
                    'Container event missing Action/status key',
                    extra={'event': event, 'image_id': image_id},
                )
                continue

            if event_image != path:
                continue

            logger.debug(
                'Container event received',
                extra={
                    'image_id': image_id,
                    'status': status,
                    'event_image': event_image,
                },
            )

            if status == 'start' or status.startswith(
                ('exec_create', 'exec_start'),
            ):
                container = find_container(
                    docker_client,
                    image_path=IMAGES[image_id].path,
                )
                if container:
                    update_container(image_id=image_id, container=container)
                else:
                    logger.warning(
                        '_monitor_events: Container not found after start event',
                        extra={'image_id': image_id, 'image_path': path},
                    )
            elif status == 'die':
                logger.info(
                    'Container die event detected - setting status to CREATED',
                    extra={'image_id': image_id, 'event_image': event_image},
                )
                store.dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=DockerItemStatus.CREATED,
                    ),
                )
                logger.info(
                    'Status updated to CREATED',
                    extra={'image_id': image_id},
                )
            elif status == 'destroy':
                logger.info(
                    'Container destroy event detected - setting status to AVAILABLE',
                    extra={'image_id': image_id, 'event_image': event_image},
                )
                store.dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=DockerItemStatus.AVAILABLE,
                    ),
                )
                logger.info(
                    'Status updated to AVAILABLE',
                    extra={'image_id': image_id},
                )
            else:
                logger.debug(
                    'Unhandled container event for this image',
                    extra={
                        'image_id': image_id,
                        'status': status,
                        'event_image': event_image,
                    },
                )


def check_container(*, image_id: str) -> None:
    """Check the container status."""
    path = IMAGES[image_id].full_path

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

            container = find_container(docker_client, image_path=IMAGES[image_id].path)
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

                _start_event_monitor(image_id, get_docker_id)
            else:
                logger.debug(
                    'Event monitor already running, skipping',
                    extra={'image_id': image_id},
                )

    to_thread(act)
