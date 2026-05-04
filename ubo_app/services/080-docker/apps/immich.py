"""Immich photo/video management Docker composition."""

from __future__ import annotations

import json
import os
import secrets as py_secrets
import string

import aiohttp

from apps._registry import COMPOSITIONS_PATH, ContainerEntry
from ubo_app.logger import logger
from ubo_app.utils import secrets


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

        if (composition_path / 'docker-compose.yml').exists() and (
            composition_path / '.env'
        ).exists():
            return True

        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml',
            ) as response:
                response.raise_for_status()
                compose_content = await response.text()
                (composition_path / 'docker-compose.yml').write_text(compose_content)

            async with session.get(
                'https://github.com/immich-app/immich/releases/latest/download/example.env',
            ) as response:
                response.raise_for_status()
                env_content = await response.text()

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

        for key, value in creds.items():
            secrets.write_secret(key=key, value=value)

        env_mappings = {
            'IMMICH_VERSION': 'release',
            'DB_DATABASE_NAME': 'immich',
            'TZ': os.environ.get('TZ', 'UTC'),
            'DB_PASSWORD': creds['IMMICH_DB_PASSWORD'],
            'DB_USERNAME': creds['IMMICH_DB_USERNAME'],
        }

        for key, value in env_mappings.items():
            env_content = env_content.replace(
                f'{key}=', f'{key}={value}\n# Original: ',
            )
            env_content = env_content.replace(f'${{{key}}}', value)

        path_replacements = {
            './library': str(composition_path / 'library'),
            './postgres': str(composition_path / 'postgres'),
        }

        for rel, abs_path in path_replacements.items():
            env_content = env_content.replace(f'={rel}', f'={abs_path}')
            env_content = env_content.replace(rel, abs_path)

        (composition_path / '.env').write_text(env_content)

        metadata = {
            'label': 'Immich',
            'icon': '',
            'instructions': """Immich is installed and running!

Access the web interface at:
http://{{hostname}}:2283

On first visit, create an admin account to start uploading your photos \
and videos.""",
            'compose_id': 'immich',
        }
        (composition_path / 'metadata.json').write_text(json.dumps(metadata))

    except Exception:
        logger.exception('Failed to prepare Immich')
        return False
    else:
        return True


ENTRY = ContainerEntry(
    id='immich',
    label='Immich',
    icon='',
    path='immich-app/immich-server:release',
    registry='ghcr.io',
    prepare=prepare_immich,
    is_composition=True,
    category='Files',
    ports={'2283/tcp': 2283},
    secret_keys=(
        'IMMICH_DB_PASSWORD',
        'IMMICH_DB_USERNAME',
    ),
)
