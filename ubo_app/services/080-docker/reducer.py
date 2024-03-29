"""Docker reducer."""

from __future__ import annotations

from dataclasses import field, replace
from typing import Any, Callable, Coroutine

from immutable import Immutable
from redux import (
    BaseEvent,
    CombineReducerAction,
    CombineReducerInitAction,
    InitAction,
    InitializationActionError,
    ReducerResult,
    combine_reducers,
)

from ubo_app.constants import DEBUG_MODE_DOCKER, DOCKER_PREFIX
from ubo_app.store.services.docker import (
    DockerAction,
    DockerImageAction,
    DockerImageEvent,
    DockerImageSetDockerIdAction,
    DockerImageSetStatusAction,
    DockerServiceState,
    DockerSetStatusAction,
    DockerState,
    ImageState,
)
from ubo_app.store.services.ip import IpUpdateAction
from ubo_app.utils.qrcode import qrcode_input

Action = InitAction | DockerAction


def service_reducer(
    state: DockerServiceState | None,
    action: Action,
) -> ReducerResult[DockerServiceState, Action, BaseEvent]:
    """Docker reducer."""
    if state is None:
        if isinstance(action, InitAction):
            return DockerServiceState()
        raise InitializationActionError(action)

    if isinstance(action, DockerSetStatusAction):
        return replace(state, status=action.status)

    return state


class ImageEntry(Immutable):
    """An image to be used in a Docker container."""

    id: str
    label: str
    icon: str
    path: str
    dependencies: list[str] | None = None
    ports: dict[str, str] = field(default_factory=dict)
    hosts: dict[str, str] = field(default_factory=dict)
    note: str | None = None
    environment_vairables: (
        dict[
            str,
            str
            | Coroutine[Any, Any, str]
            | Callable[[], str | Coroutine[Any, Any, str]],
        ]
        | None
    ) = None
    network_mode: str = 'bridge'
    volumes: list[str] | None = None
    command: (
        str
        | Coroutine[Any, Any, str]
        | Callable[[], str | Coroutine[Any, Any, str]]
        | None
    ) = None


IMAGES = {
    image.id: image
    for image in [
        ImageEntry(
            id='home_assistant',
            label='Home Assistant',
            icon='󰟐',
            path=DOCKER_PREFIX + 'homeassistant/home-assistant:stable',
            ports={'8123/tcp': '8123'},
        ),
        ImageEntry(
            id='home_bridge',
            label='Home Bridge',
            icon='󰘘',
            path=DOCKER_PREFIX + 'homebridge/homebridge:latest',
        ),
        ImageEntry(
            id='portainer',
            label='Portainer',
            icon='',
            path=DOCKER_PREFIX + 'portainer/portainer-ce:latest',
            volumes=['/var/run/docker.sock:/var/run/docker.sock'],
        ),
        ImageEntry(
            id='pi_hole',
            label='Pi-hole',
            icon='󰇖',
            environment_vairables={'WEBPASSWORD': 'admin'},
            note='Password: admin',
            path=DOCKER_PREFIX + 'pihole/pihole:latest',
        ),
        ImageEntry(
            id='ollama',
            label='Ollama',
            icon='󰳆',
            path=DOCKER_PREFIX + 'ollama/ollama:latest',
            ports={'11434/tcp': '11434'},
        ),
        ImageEntry(
            id='open_webui',
            label='Open WebUI',
            icon='󰾔',
            path=DOCKER_PREFIX + 'ghcr.io/open-webui/open-webui:main',
            dependencies=['ollama'],
            network_mode='container:ollama',
            ports={'8080/tcp': '8080'},
            hosts={'host.docker.internal': 'ollama'},
        ),
        ImageEntry(
            id='ngrok',
            label='Ngrok',
            icon='󰛶',
            network_mode='host',
            path=DOCKER_PREFIX + 'ngrok/ngrok:latest',
            environment_vairables={
                'NGROK_AUTHTOKEN': lambda: qrcode_input(
                    r'^[a-zA-Z0-9]{20,30}_[a-zA-Z0-9]{20,30}$',
                    resolver=lambda code, _: code,
                    prompt='Enter the Ngrok Auth Token',
                ),
            },
            command=lambda: qrcode_input(
                '',
                resolver=lambda code, _: code,
                prompt='Enter the command, for example: `http 80` or `tcp 22`',
            ),
        ),
        *(
            [
                ImageEntry(
                    id='alpine',
                    label='Alpine',
                    icon='',
                    path=DOCKER_PREFIX + 'alpine:latest',
                ),
            ]
            if DEBUG_MODE_DOCKER
            else []
        ),
    ]
}
IMAGE_IDS = list(IMAGES.keys())


def image_reducer(
    state: ImageState | None,
    action: DockerImageAction | CombineReducerAction | IpUpdateAction,
) -> ImageState:
    """Image reducer."""
    if state is None:
        if isinstance(action, CombineReducerInitAction):
            image = IMAGES[action.key]
            return ImageState(
                id=image.id,
                label=image.label,
                icon=image.icon,
                path=image.path,
            )
        raise InitializationActionError(action)

    if isinstance(action, IpUpdateAction):
        return replace(
            state,
            ip_addresses=[
                ip for interface in action.interfaces for ip in interface.ip_addresses
            ],
        )

    if not isinstance(action, DockerImageAction) or action.image != state.id:
        return state

    if isinstance(action, DockerImageSetStatusAction):
        return replace(
            state,
            status=action.status,
            ports=action.ports if action.ports else state.ports,
            container_ip=action.ip,
        )

    if isinstance(action, DockerImageSetDockerIdAction):
        return replace(state, docker_id=action.docker_id)

    return state


reducer, reducer_id = combine_reducers(
    state_type=DockerState,
    action_type=DockerImageAction,
    event_type=DockerImageEvent,
    service=service_reducer,
    **{image: image_reducer for image in IMAGE_IDS},
)
