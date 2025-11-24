"""Images to be used in Docker containers."""

from __future__ import annotations

import asyncio
import json
import os
import secrets as py_secrets
import string
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import aiohttp
from immutable import Immutable

from ubo_app.constants import (
    CONFIG_PATH,
    DEBUG_DOCKER,
    GRPC_ENVOY_LISTEN_PORT,
    GRPC_LISTEN_PORT,
)
from ubo_app.logger import logger
from ubo_app.store.input.types import QRCodeInputDescription, WebUIInputDescription
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils import IS_RPI, secrets
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

ENVOY_TEMPLATE_PATH = Path(__file__).parent / 'assets' / 'envoy.yaml.tmpl'
ENVOY_CONFIG_PATH = Path(__file__).parent / 'assets' / 'envoy.yaml'
COMPOSITIONS_PATH = CONFIG_PATH / 'docker_compositions'


async def prepare_envoy() -> bool:
    """Prepare Envoy for gRPC."""
    process = await asyncio.create_subprocess_exec(
        '/usr/bin/env',
        'envsubst',
        env={
            'GRPC_ENVOY_LISTEN_PORT': f'{GRPC_ENVOY_LISTEN_PORT}',
            'GRPC_LISTEN_PORT': f'{GRPC_LISTEN_PORT}',
            'GRPC_SERVER_HOST': '127.0.0.1' if IS_RPI else 'host.docker.internal',
            **os.environ,
        },
        stdin=ENVOY_TEMPLATE_PATH.open(),
        stdout=ENVOY_CONFIG_PATH.open('w'),
    )
    await process.wait()
    return process.returncode == 0


async def prepare_immich() -> bool:
    """Prepare Immich for Docker Composition."""
    try:
        composition_id = 'immich'
        composition_path = COMPOSITIONS_PATH / composition_id
        logger.info(
            'Preparing Immich composition',
            extra={'composition_path': str(composition_path)},
        )
        composition_path.mkdir(exist_ok=True, parents=True)

        # Check if already set up
        if (composition_path / 'docker-compose.yml').exists() and (
            composition_path / '.env'
        ).exists():
            return True

        # Download docker-compose.yml
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml',
            ) as response:
                response.raise_for_status()
                compose_content = await response.text()
                (composition_path / 'docker-compose.yml').write_text(compose_content)

            # Download .env template
            async with session.get(
                'https://github.com/immich-app/immich/releases/latest/download/example.env',
            ) as response:
                response.raise_for_status()
                env_content = await response.text()

        # Generate credentials
        creds = {
            'IMMICH_DB_PASSWORD': ''.join(
                py_secrets.choice(string.ascii_letters + string.digits)
                for _ in range(32)
            ),
            'IMMICH_DB_USERNAME': 'user_'
            + ''.join(
                py_secrets.choice(string.ascii_lowercase + string.digits)
                for _ in range(16)
            ),
        }

        # Save credentials
        for key, value in creds.items():
            secrets.write_secret(key=key, value=value)

        # Process .env content
        env_mappings = {
            'IMMICH_VERSION': 'release',
            'DB_DATABASE_NAME': 'immich',
            'TZ': os.environ.get('TZ', 'UTC'),
            'DB_PASSWORD': creds['IMMICH_DB_PASSWORD'],
            'DB_USERNAME': creds['IMMICH_DB_USERNAME'],
        }

        for key, value in env_mappings.items():
            env_content = env_content.replace(f'{key}=', f'{key}={value}\n# Original: ')
            env_content = env_content.replace(f'${{{key}}}', value)

        # Path replacements
        path_replacements = {
            './library': str(composition_path / 'library'),
            './postgres': str(composition_path / 'postgres'),
        }

        for rel, abs_path in path_replacements.items():
            env_content = env_content.replace(f'={rel}', f'={abs_path}')
            env_content = env_content.replace(rel, abs_path)

        (composition_path / '.env').write_text(env_content)

        # Create metadata.json
        metadata = {
            'label': 'Immich',
            'icon': '',
            'instructions': """Immich is installed and running!

Access the web interface at:
http://{{hostname}}:2283

On first visit, create an admin account to start uploading your photos and videos.""",
            'compose_id': 'immich',
        }
        (composition_path / 'metadata.json').write_text(json.dumps(metadata))

    except Exception:
        logger.exception('Failed to prepare Immich')
        return False
    else:
        return True


class ContainerEntry(Immutable):
    """Container entry."""

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
    hostname: str | None = None
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
    dns: list[str] | None = None
    volumes: list[str] | None = None
    command: (
        str
        | list[str]
        | Callable[[], str | list[str] | Coroutine[Any, Any, str | list[str]]]
        | None
    ) = None
    prepare: Callable[[], Coroutine[Any, Any, bool] | bool] | None = None
    is_composition: bool = False

    @property
    def full_path(self) -> str:
        """Get full image path including registry if specified."""
        return f'{self.registry}/{self.path}'


IMAGES = {
    image.id: image
    for image in [
        ContainerEntry(
            id='home_assistant',
            label='Home Assistant',
            icon='󰟐',
            path='homeassistant/home-assistant:stable',
            registry='docker.io',
            ports={'8123/tcp': 8123},
        ),
        ContainerEntry(
            id='home_bridge',
            label='Home Bridge',
            icon='󰘘',
            path='homebridge/homebridge:latest',
            registry='docker.io',
        ),
        ContainerEntry(
            id='portainer',
            label='Portainer',
            icon='',
            path='portainer/portainer-ce:latest',
            registry='docker.io',
            volumes=['/var/run/docker.sock:/var/run/docker.sock'],
        ),
        ContainerEntry(
            id='pi_hole',
            label='Pi-hole',
            icon='󰇖',
            hostname='pi.hole',
            note='Password: admin',
            path='pihole/pihole:latest',
            ports={
                '53/tcp': 53,
                '53/udp': 53,
                '80/tcp': 80,
                '443/tcp': 443,
            },
            dns=['127.0.0.1', '1.1.1.1'],
            registry='docker.io',
        ),
        ContainerEntry(
            id='ollama',
            label='Ollama',
            icon='󰳆',
            path='ollama/ollama:latest',
            registry='docker.io',
            ports={'11434/tcp': 11434},
        ),
        ContainerEntry(
            id='open_webui',
            label='Open WebUI',
            icon='󰾔',
            path='open-webui/open-webui:main',
            registry='ghcr.io',
            dependencies=['ollama'],
            ports={'8080/tcp': 8080},
            hosts={'host.docker.internal': 'host-gateway'},
        ),
        ContainerEntry(
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
                    descriptions=[
                        QRCodeInputDescription(
                            instructions=ReadableInformation(
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
                            pattern=rf'^[a-zA-Z0-9]{20, 30}_[a-zA-Z0-9]{20, 30}$',
                        ),
                        WebUIInputDescription(),
                    ],
                ),
            },
            command=lambda: ubo_input(
                resolver=lambda code, _: code,
                prompt='Enter the command, for example: `http 80` or `tcp 22`',
                descriptions=[
                    QRCodeInputDescription(
                        instructions=ReadableInformation(
                            text='This is the command you would enter when running '
                            'ngrok. Refer to ngrok documentation for further '
                            'information',
                            picovoice_text="""\
This is the command you would enter when running {ngrok|EH N G EH R AA K}.
Refer to {ngrok|EH N G EH R AA K} documentation for further information""",
                        ),
                    ),
                    WebUIInputDescription(),
                ],
            ),
        ),
        ContainerEntry(
            id='immich',
            label='Immich',
            icon='',
            path='immich-app/immich-server:release',
            registry='ghcr.io',
            prepare=prepare_immich,
            is_composition=True,
            ports={'2283/tcp': 2283},
        ),
        *(
            [
                ContainerEntry(
                    id='alpine',
                    label='Alpine',
                    icon='',
                    path='alpine:latest',
                    registry='docker.io',
                ),
            ]
            if DEBUG_DOCKER
            else []
        ),
        ContainerEntry(
            id='envoy_grpc',
            label='Envoy for gRPC',
            icon='󱂇',
            path='thegrandpkizzle/envoy:1.26.1',
            prepare=prepare_envoy,
            command=['--config-path', 'envoy.yaml'],
            registry='docker.io',
            volumes=[
                f'{ENVOY_CONFIG_PATH}:/envoy.yaml',
            ],
            **cast(
                'Any',
                {'network_mode': 'host'}
                if IS_RPI
                else {
                    'ports': {
                        f'{GRPC_ENVOY_LISTEN_PORT}/tcp': GRPC_ENVOY_LISTEN_PORT,
                    },
                },
            ),
        ),
    ]
}
