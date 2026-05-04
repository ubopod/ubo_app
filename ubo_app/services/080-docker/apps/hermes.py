"""Hermes Agent + Dashboard + WebUI Docker composition."""

from __future__ import annotations

import json
import secrets as py_secrets
from typing import TYPE_CHECKING

import aiohttp

from apps._registry import COMPOSITIONS_PATH, ContainerEntry
from ubo_app.logger import logger
from ubo_app.utils import secrets

if TYPE_CHECKING:
    from pathlib import Path

HERMES_COMPOSITION_ID = 'hermes'
HERMES_COMPOSE_URL = (
    'https://raw.githubusercontent.com/nesquena/hermes-webui'
    '/master/docker-compose.three-container.yml'
)
HERMES_GATEWAY_PORT = 8642
HERMES_DASHBOARD_PORT = 9119
HERMES_WEBUI_PORT = 8787
HERMES_API_SERVER_KEY_SECRET = 'hermes_api_server_key'  # noqa: S105


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _patch_compose(content: str) -> str:
    """Patch the upstream compose file for headless Ubo deployment.

    - Replace workspace bind mount with ./workspace for self-contained deploy.
    - Fix hermes-agent HERMES_HOME to /opt/data (avoids privilege-drop bug).
    """
    patched = content.replace('~/workspace:/workspace', './workspace:/workspace')
    patched = patched.replace(
        '${HERMES_WORKSPACE:-~/workspace}:/workspace',
        './workspace:/workspace',
    )
    patched = patched.replace(
        '- hermes-home:/root/.hermes',
        '- hermes-home:/opt/data',
    )
    patched = patched.replace(
        '- hermes-home:/home/hermes/.hermes',
        '- hermes-home:/opt/data',
    )
    patched = patched.replace(
        '- HERMES_HOME=/root/.hermes',
        '- HERMES_HOME=/opt/data',
    )
    patched = patched.replace(
        '- HERMES_HOME=/home/hermes/.hermes',
        '- HERMES_HOME=/opt/data',
    )
    return _inject_api_server_env(patched)


def _inject_api_server_env(content: str) -> str:
    """Ensure the Hermes gateway API server env vars are in compose."""
    required_env_lines = [
        '      - API_SERVER_ENABLED=true',
        '      - API_SERVER_KEY=${HERMES_API_SERVER_KEY}',
        '      - API_SERVER_HOST=0.0.0.0',
        '      - GATEWAY_ALLOW_ALL_USERS=true',
    ]
    missing_env_lines = [
        line
        for line in required_env_lines
        if line.split('=', maxsplit=1)[0].strip() not in content
    ]
    if not missing_env_lines:
        return content

    needle = '- HERMES_HOME=/opt/data'
    if needle not in content:
        logger.warning('Unable to inject Hermes API server env vars')
        return content

    replacement = '\n'.join([needle, *missing_env_lines])
    return content.replace(needle, replacement, 1)


def _get_or_create_api_server_key() -> str:
    """Return the persisted Hermes API server key, creating it if needed."""
    key = secrets.read_secret(HERMES_API_SERVER_KEY_SECRET)
    if key:
        return key

    key = py_secrets.token_urlsafe(32)
    secrets.write_secret(key=HERMES_API_SERVER_KEY_SECRET, value=key)
    return key


def _write_hermes_env(composition_path: Path) -> None:
    """Write compose env for Hermes.

    UID/GID are set to 10000 (the hermes user inside the image) so the WebUI
    container chowns the shared hermes-home volume to the correct user.
    Setting UID=0 would cause the WebUI to chown everything to root, making
    the volume inaccessible to the hermes-agent (which runs as UID 10000).
    """
    api_server_key = _get_or_create_api_server_key()
    composition_path.joinpath('.env').write_text(
        'UID=10000\n'
        'GID=10000\n'
        'HERMES_UID=10000\n'
        'HERMES_GID=10000\n'
        f'HERMES_API_SERVER_KEY={api_server_key}\n',
    )


# ---------------------------------------------------------------------------
# Prepare / reconfigure
# ---------------------------------------------------------------------------


def _is_hermes_configured() -> bool:
    composition_path = COMPOSITIONS_PATH / HERMES_COMPOSITION_ID
    return (
        (composition_path / 'docker-compose.yml').exists()
        and (composition_path / '.env').exists()
    )


async def prepare_hermes() -> bool:
    """Prepare Hermes Agent + Dashboard + WebUI for Docker Composition."""
    try:
        composition_path = COMPOSITIONS_PATH / HERMES_COMPOSITION_ID
        logger.info(
            'Preparing Hermes composition',
            extra={'composition_path': str(composition_path)},
        )

        composition_path.mkdir(exist_ok=True, parents=True)
        (composition_path / 'workspace').mkdir(exist_ok=True, parents=True)

        compose_path = composition_path / 'docker-compose.yml'
        if compose_path.exists():
            compose_content = compose_path.read_text()
        else:
            async with (
                aiohttp.ClientSession() as session,
                session.get(HERMES_COMPOSE_URL) as response,
            ):
                response.raise_for_status()
                compose_content = await response.text()

        compose_content = _patch_compose(compose_content)
        compose_path.write_text(compose_content)

        _write_hermes_env(composition_path)

        metadata = {
            'label': 'Hermes Agent',
            'icon': '󱚣',
            'instructions': (
                'Hermes Agent is installed and running!\n\n'
                f'Gateway: http://{{{{hostname}}}}:{HERMES_GATEWAY_PORT}\n'
                f'Dashboard: http://{{{{hostname}}}}:{HERMES_DASHBOARD_PORT}\n'
                f'WebUI: http://{{{{hostname}}}}:{HERMES_WEBUI_PORT}\n\n'
                'Use the WebUI to chat with Hermes, and use the dashboard to '
                'monitor agent activity, sessions, and resource usage.'
            ),
            'compose_id': HERMES_COMPOSITION_ID,
        }
        (composition_path / 'metadata.json').write_text(json.dumps(metadata))

    except Exception:
        logger.exception('Failed to prepare Hermes')
        return False
    else:
        return True


ENTRY = ContainerEntry(
    id=HERMES_COMPOSITION_ID,
    label='Hermes Agent',
    icon='󱚣',
    path='nesquena/hermes-webui:latest',
    registry='ghcr.io',
    prepare=prepare_hermes,
    is_composition=True,
    category='AI Agents',
    ports={
        f'{HERMES_GATEWAY_PORT}/tcp': HERMES_GATEWAY_PORT,
        f'{HERMES_DASHBOARD_PORT}/tcp': HERMES_DASHBOARD_PORT,
        f'{HERMES_WEBUI_PORT}/tcp': HERMES_WEBUI_PORT,
    },
)
