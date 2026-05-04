"""n8n workflow automation Docker composition."""

from __future__ import annotations

import json
import secrets as py_secrets
import string

import aiohttp

from apps._registry import COMPOSITIONS_PATH, ContainerEntry
from ubo_app.logger import logger
from ubo_app.utils import secrets


async def prepare_n8n() -> bool:
    """Prepare n8n for Docker Composition."""
    try:
        composition_id = 'n8n'
        composition_path = COMPOSITIONS_PATH / composition_id
        logger.info(
            'Preparing n8n composition',
            extra={'composition_path': str(composition_path)},
        )
        composition_path.mkdir(exist_ok=True, parents=True)

        if (composition_path / 'docker-compose.yml').exists() and (
            composition_path / '.env'
        ).exists():
            return True

        async with aiohttp.ClientSession() as session:
            base_url = (
                'https://raw.githubusercontent.com/n8n-io/n8n-hosting'
                '/main/docker-compose/withPostgres'
            )
            async with session.get(
                f'{base_url}/docker-compose.yml',
            ) as response:
                response.raise_for_status()
                compose_content = await response.text()
                (composition_path / 'docker-compose.yml').write_text(
                    compose_content,
                )

            async with session.get(
                f'{base_url}/init-data.sh',
            ) as response:
                response.raise_for_status()
                init_script = await response.text()
                init_path = composition_path / 'init-data.sh'
                init_path.write_text(init_script)
                init_path.chmod(0o755)

        runners_auth_token = ''.join(
            py_secrets.choice(string.ascii_letters + string.digits)
            for _ in range(64)
        )
        creds = {
            'N8N_DB_PASSWORD': ''.join(
                py_secrets.choice(string.ascii_letters + string.digits)
                for _ in range(32)
            ),
            'N8N_DB_USER': 'user_'
            + ''.join(
                py_secrets.choice(string.ascii_lowercase + string.digits)
                for _ in range(16)
            ),
            'N8N_DB_NON_ROOT_PASSWORD': ''.join(
                py_secrets.choice(string.ascii_letters + string.digits)
                for _ in range(32)
            ),
            'N8N_DB_NON_ROOT_USER': 'n8n_'
            + ''.join(
                py_secrets.choice(string.ascii_lowercase + string.digits)
                for _ in range(16)
            ),
        }

        for key, value in creds.items():
            secrets.write_secret(key=key, value=value)

        env_content = (
            f"POSTGRES_USER={creds['N8N_DB_USER']}\n"
            f"POSTGRES_PASSWORD={creds['N8N_DB_PASSWORD']}\n"
            f"POSTGRES_DB=n8n\n"
            f"\n"
            f"POSTGRES_NON_ROOT_USER={creds['N8N_DB_NON_ROOT_USER']}\n"
            f"POSTGRES_NON_ROOT_PASSWORD={creds['N8N_DB_NON_ROOT_PASSWORD']}\n"
            f"\n"
            f"N8N_VERSION=latest\n"
            f"RUNNERS_AUTH_TOKEN={runners_auth_token}\n"
            f"N8N_SECURE_COOKIE=false\n"
        )
        (composition_path / '.env').write_text(env_content)

        metadata = {
            'label': 'n8n',
            'icon': '󱂚',
            'instructions': """n8n is installed and running!

Access the workflow editor at:
http://{{hostname}}:5678

On first visit, create an account to start building automations.""",
            'compose_id': 'n8n',
        }
        (composition_path / 'metadata.json').write_text(json.dumps(metadata))

    except Exception:
        logger.exception('Failed to prepare n8n')
        return False
    else:
        return True


ENTRY = ContainerEntry(
    id='n8n',
    label='n8n',
    icon='󱂚',
    path='n8nio/n8n:latest',
    registry='docker.n8n.io',
    prepare=prepare_n8n,
    is_composition=True,
    category='AI Agents',
    ports={'5678/tcp': 5678},
    secret_keys=(
        'N8N_DB_PASSWORD',
        'N8N_DB_USER',
        'N8N_DB_NON_ROOT_PASSWORD',
        'N8N_DB_NON_ROOT_USER',
    ),
)
