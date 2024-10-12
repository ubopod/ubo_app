"""Images to be used in Docker containers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


from dataclasses import field
from typing import TYPE_CHECKING

from immutable import Immutable

from ubo_app.constants import DEBUG_MODE_DOCKER, DOCKER_PREFIX
from ubo_app.store.services.notifications import NotificationExtraInformation
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


class ImageEntry(Immutable):
    """An image to be used in a Docker container."""

    id: str
    label: str
    icon: str
    path: str
    registry: str
    dependencies: list[str] | None = None
    ports: dict[str, int | list[int] | tuple[str, int] | None] = field(
        default_factory=dict,
    )
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
            ports={'8123/tcp': 8123},
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
            ports={'11434/tcp': 11434},
        ),
        ImageEntry(
            id='open_webui',
            label='Open WebUI',
            icon='󰾔',
            path=DOCKER_PREFIX + 'open-webui/open-webui:main',
            registry='ghcr.io',
            dependencies=['ollama'],
            ports={'8080/tcp': 8080},
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
                'NGROK_AUTHTOKEN': lambda: ubo_input(
                    resolver=lambda code, _: code,
                    prompt='Enter the Ngrok Auth Token',
                    extra_information=NotificationExtraInformation(
                        text="""\
Follow these steps:

1. Login to your ngrok account.
2. Get the authentication token from the dashboard.
3. Convert it to QR code.
4. Scan QR code to input the token.""",
                        picovoice_text="""\
Follow these steps:

1. Login to your {ngrok|EH N G EH R AA K} account
2. Get the authentication token from the dashboard
3. Convert it to {QR|K Y UW AA R} code
4. Scan QR code to input the token""",
                    ),
                    pattern=rf'^[a-zA-Z0-9]{20,30}_[a-zA-Z0-9]{20,30}$',
                ),
            },
            command=lambda: ubo_input(
                resolver=lambda code, _: code,
                prompt='Enter the command, for example: `http 80` or `tcp 22`',
                extra_information=NotificationExtraInformation(
                    text='This is the command you would enter when running ngrok. '
                    'Refer to ngrok documentation for further information',
                    picovoice_text="""\
This is the command you would enter when running {ngrok|EH N G EH R AA K}.
Refer to {ngrok|EH N G EH R AA K} documentation for further information""",
                ),
                fields=[],
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
