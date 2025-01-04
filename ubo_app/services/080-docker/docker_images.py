"""Images to be used in Docker containers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


from dataclasses import field
from typing import TYPE_CHECKING

from immutable import Immutable

from ubo_app.constants import DEBUG_MODE_DOCKER, GRPC_ENVOY_LISTEN_PORT
from ubo_app.store.services.notifications import NotificationExtraInformation
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


class CompositionEntry(Immutable):
    """Composition entry."""

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
    command: str | Callable[[], str | Coroutine[Any, Any, str]] | None = None


IMAGES = {
    image.id: image
    for image in [
        CompositionEntry(
            id='home_assistant',
            label='Home Assistant',
            icon='󰟐',
            path='homeassistant/home-assistant:stable',
            registry='docker.io',
            ports={'8123/tcp': 8123},
        ),
        CompositionEntry(
            id='home_bridge',
            label='Home Bridge',
            icon='󰘘',
            path='homebridge/homebridge:latest',
            registry='docker.io',
        ),
        CompositionEntry(
            id='portainer',
            label='Portainer',
            icon='',
            path='portainer/portainer-ce:latest',
            registry='docker.io',
            volumes=['/var/run/docker.sock:/var/run/docker.sock'],
        ),
        CompositionEntry(
            id='pi_hole',
            label='Pi-hole',
            icon='󰇖',
            environment_vairables={'WEBPASSWORD': 'admin'},
            note='Password: admin',
            path='pihole/pihole:latest',
            registry='docker.io',
        ),
        CompositionEntry(
            id='ollama',
            label='Ollama',
            icon='󰳆',
            path='ollama/ollama:latest',
            registry='docker.io',
            ports={'11434/tcp': 11434},
        ),
        CompositionEntry(
            id='open_webui',
            label='Open WebUI',
            icon='󰾔',
            path='open-webui/open-webui:main',
            registry='ghcr.io',
            dependencies=['ollama'],
            ports={'8080/tcp': 8080},
            hosts={'host.docker.internal': 'ollama'},
        ),
        CompositionEntry(
            id='ngrok',
            label='Ngrok',
            icon='󰛶',
            network_mode='host',
            path='ngrok/ngrok:latest',
            registry='docker.io',
            environment_vairables={
                'NGROK_AUTHTOKEN': lambda: ubo_input(
                    resolver=lambda code, _: code,
                    prompt='Enter the Ngrok Auth Token',
                    qr_code_generation_instructions=NotificationExtraInformation(
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
                qr_code_generation_instructions=NotificationExtraInformation(
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
                CompositionEntry(
                    id='alpine',
                    label='Alpine',
                    icon='',
                    path='alpine:latest',
                    registry='docker.io',
                ),
            ]
            if DEBUG_MODE_DOCKER
            else []
        ),
        CompositionEntry(
            id='envoy_grpc',
            label='Envoy for gRPC',
            icon='󱂇',
            path='envoyproxy/envoy-distroless:v1.32-latest',
            registry='docker.io',
            volumes=[],
            ports={f'{GRPC_ENVOY_LISTEN_PORT}/tcp': GRPC_ENVOY_LISTEN_PORT},
        ),
    ]
}
