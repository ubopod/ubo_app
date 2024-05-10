"""Docker reducer."""

from __future__ import annotations

from dataclasses import field, replace
from typing import TYPE_CHECKING, Any

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
    DockerRemoveUsernameAction,
    DockerServiceState,
    DockerSetStatusAction,
    DockerState,
    DockerStoreUsernameAction,
    ImageState,
)
from ubo_app.utils.qrcode import qrcode_input

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ubo_app.store.services.ip import IpUpdateInterfacesAction

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

    if isinstance(action, DockerStoreUsernameAction):
        return replace(
            state,
            usernames={**state.usernames, action.registry: action.username},
        )

    if isinstance(action, DockerRemoveUsernameAction):
        return replace(
            state,
            usernames={
                registry: username
                for registry, username in state.usernames.items()
                if registry != action.registry
            },
        )

    return state


class ImageEntry(Immutable):
    """An image to be used in a Docker container."""

    id: str
    label: str
    icon: str
    path: str
    registry: str
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
            registry='docker.io',
            ports={'8123/tcp': '8123'},
        ),
        ImageEntry(
            id='home_bridge',
            label='Home Bridge',
            icon='󰘘',
            path=DOCKER_PREFIX + 'homebridge/homebridge:latest',
            registry='docker.io',
        ),
        ImageEntry(
            id='portainer',
            label='Portainer',
            icon='',
            path=DOCKER_PREFIX + 'portainer/portainer-ce:latest',
            registry='docker.io',
            volumes=['/var/run/docker.sock:/var/run/docker.sock'],
        ),
        ImageEntry(
            id='pi_hole',
            label='Pi-hole',
            icon='󰇖',
            environment_vairables={'WEBPASSWORD': 'admin'},
            note='Password: admin',
            path=DOCKER_PREFIX + 'pihole/pihole:latest',
            registry='docker.io',
        ),
        ImageEntry(
            id='ollama',
            label='Ollama',
            icon='󰳆',
            path=DOCKER_PREFIX + 'ollama/ollama:latest',
            registry='docker.io',
            ports={'11434/tcp': '11434'},
        ),
        ImageEntry(
            id='open_webui',
            label='Open WebUI',
            icon='󰾔',
            path=DOCKER_PREFIX + 'open-webui/open-webui:main',
            registry='ghcr.io',
            dependencies=['ollama'],
            ports={'8080/tcp': '8080'},
            hosts={'host.docker.internal': 'ollama'},
        ),
        ImageEntry(
            id='ngrok',
            label='Ngrok',
            icon='󰛶',
            network_mode='host',
            path=DOCKER_PREFIX + 'ngrok/ngrok:latest',
            registry='docker.io',
            environment_vairables={
                'NGROK_AUTHTOKEN': lambda: qrcode_input(
                    r'^[a-zA-Z0-9]{20,30}_[a-zA-Z0-9]{20,30}$',
                    resolver=lambda code, _: code,
                    prompt='Enter the Ngrok Auth Token',
                    extra_information="""\
Follow these steps:

1. Login to your {ngrok|EH N G EH R AA K} account
2. Get the authentication token from the dashboard
3. Convert it to {QR|K Y UW AA R} code
4. Scan QR code to input the token""",
                ),
            },
            command=lambda: qrcode_input(
                '',
                resolver=lambda code, _: code,
                prompt='Enter the command, for example: `http 80` or `tcp 22`',
                extra_information="""\
This is the command you would enter when running {ngrok|EH N G EH R AA K}.
Refer to {ngrok|EH N G EH R AA K} documentation for further information""",
            ),
        ),
        *(
            [
                ImageEntry(
                    id='alpine',
                    label='Alpine',
                    icon='',
                    path=DOCKER_PREFIX + 'alpine:latest',
                    registry='docker.io',
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
    action: DockerImageAction | CombineReducerAction | IpUpdateInterfacesAction,
) -> ImageState:
    """Image reducer."""
    if state is None:
        if isinstance(action, CombineReducerInitAction):
            image = IMAGES[action.key]
            return ImageState(id=image.id)
        raise InitializationActionError(action)

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
