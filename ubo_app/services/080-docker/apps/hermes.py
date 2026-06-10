"""Hermes Agent + Dashboard + WebUI Docker composition."""

from __future__ import annotations

import json
import re
import secrets as py_secrets
from typing import TYPE_CHECKING

import aiohttp

from apps._registry import COMPOSITIONS_PATH, ContainerEntry
from ubo_app.constants import CONFIG_PATH
from ubo_app.constants.assistant import (
    GENERIC_LLM_PROVIDER_API_KEY_SECRET_TEMPLATE,
    GENERIC_LLM_PROVIDER_BASE_URL_SECRET_TEMPLATE,
    GENERIC_LLM_PROVIDER_MODEL_SECRET_TEMPLATE,
)
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantAddGenericLLMProviderAction,
    AssistantRemoveGenericLLMProviderAction,
)
from ubo_app.utils import secrets

if TYPE_CHECKING:
    from pathlib import Path

HERMES_COMPOSITION_ID = 'hermes'
# Persistent host directory for all Hermes state, kept outside the composition
# directory so neither `docker compose down -v` nor the composition-directory
# removal on uninstall can destroy it. This decouples config/skills/sessions/
# memories/API keys from the disposable Docker image.
HERMES_DATA_PATH = CONFIG_PATH / 'hermes-data'
HERMES_COMPOSE_URL = (
    'https://raw.githubusercontent.com/nesquena/hermes-webui'
    '/master/docker-compose.three-container.yml'
)
HERMES_GATEWAY_PORT = 8642
HERMES_DASHBOARD_PORT = 9119
HERMES_WEBUI_PORT = 8787
HERMES_API_SERVER_KEY_SECRET = 'hermes_api_server_key'  # noqa: S105

# Auto-registered assistant LLM provider backed by the Hermes gateway's
# OpenAI-compatible API server.
HERMES_LLM_PROVIDER_ID = 'hermes'
HERMES_LLM_PROVIDER_LABEL = 'Hermes'
HERMES_LLM_BASE_URL = f'http://127.0.0.1:{HERMES_GATEWAY_PORT}/v1'
HERMES_LLM_MODEL = 'hermes-agent'
HERMES_LLM_PROVIDER_SECRET_KEYS = (
    GENERIC_LLM_PROVIDER_BASE_URL_SECRET_TEMPLATE.format(
        provider_id=HERMES_LLM_PROVIDER_ID,
    ),
    GENERIC_LLM_PROVIDER_API_KEY_SECRET_TEMPLATE.format(
        provider_id=HERMES_LLM_PROVIDER_ID,
    ),
    GENERIC_LLM_PROVIDER_MODEL_SECRET_TEMPLATE.format(
        provider_id=HERMES_LLM_PROVIDER_ID,
    ),
)


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _patch_compose(content: str) -> str:
    """Patch the upstream compose file for headless Ubo deployment.

    Convert the named ``hermes-home`` volume and the ``/workspace`` bind mount
    into host bind mounts under ``HERMES_DATA_PATH`` (which lives outside the
    composition directory). This decouples all Hermes state — config, skills,
    sessions, memories, API keys — from the Docker image so it survives
    ``docker compose down -v`` and an app delete/reinstall.

    Regexes (not literal strings) are used so the patch keeps working when the
    upstream compose renames the in-container mount targets. The
    ``hermes-agent-src`` volume is left untouched: it is image-derived source
    code, not user data.
    """
    data_path = HERMES_DATA_PATH / 'data'
    workspace_path = HERMES_DATA_PATH / 'workspace'
    # Point every `hermes-home:<target>` mount at the same shared host dir,
    # preserving the container-side path so all three containers keep sharing
    # state (agent/dashboard at /opt/data, webui at /home/hermeswebui/.hermes).
    patched = re.sub(
        r'- hermes-home:(\S+)',
        rf'- {data_path}:\1',
        content,
    )
    # Redirect whatever is bind-mounted at /workspace to our persistent dir,
    # regardless of the upstream source expression (e.g. ~/workspace or
    # ${HERMES_WORKSPACE:-${HOME}/workspace}).
    patched = re.sub(
        r'- \S+:/workspace\b',
        rf'- {workspace_path}:/workspace',
        patched,
    )
    return _inject_api_server_env(patched)


def _inject_api_server_env(content: str) -> str:
    """Ensure the Hermes gateway API server env vars are in compose.

    The vars are injected right after the agent service's ``HERMES_HOME`` env
    line. The first ``HERMES_HOME`` in the file belongs to ``hermes-agent``
    (which runs the gateway); the dashboard's identical line comes later, so a
    single replacement targets the agent only. ``HERMES_HOME`` is matched by
    name — not a fixed value — so this keeps working when upstream changes the
    home path (e.g. ``/opt/data`` → ``/home/hermes/.hermes``).
    """
    required_env_lines = [
        '- API_SERVER_ENABLED=true',
        '- API_SERVER_KEY=${HERMES_API_SERVER_KEY}',
        '- API_SERVER_HOST=0.0.0.0',
        '- GATEWAY_ALLOW_ALL_USERS=true',
    ]
    missing_env_lines = [
        line
        for line in required_env_lines
        if line.split('=', maxsplit=1)[0].strip() not in content
    ]
    if not missing_env_lines:
        return content

    match = re.search(r'^([ \t]*)- HERMES_HOME=.*$', content, flags=re.MULTILINE)
    if match is None:
        logger.warning('Unable to inject Hermes API server env vars')
        return content

    indent = match.group(1)
    needle = match.group(0)
    replacement = '\n'.join(
        [needle, *(f'{indent}{line}' for line in missing_env_lines)],
    )
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
        'API_SERVER_ENABLED=true\n'
        f'HERMES_API_SERVER_KEY={api_server_key}\n',
    )


def _register_assistant_provider(api_server_key: str) -> None:
    """Register the Hermes gateway as a named generic LLM provider.

    Writes the per-provider credentials and upserts the provider entry so it
    shows up under Assistant → Language Model without any manual setup. It
    is *not* auto-selected — the user picks it like any other provider.
    """
    base_url_key, api_key_key, model_key = HERMES_LLM_PROVIDER_SECRET_KEYS
    secrets.write_secret(key=base_url_key, value=HERMES_LLM_BASE_URL)
    secrets.write_secret(key=api_key_key, value=api_server_key)
    secrets.write_secret(key=model_key, value=HERMES_LLM_MODEL)
    store.dispatch(
        AssistantAddGenericLLMProviderAction(
            provider_id=HERMES_LLM_PROVIDER_ID,
            label=HERMES_LLM_PROVIDER_LABEL,
        ),
    )


def _cleanup_hermes() -> None:
    """Deregister the Hermes assistant LLM provider on uninstall.

    The provider's secrets are cleared by the assistant service's
    removed-event handler (and ``ENTRY.secret_keys`` as a fallback when the
    assistant service isn't loaded).
    """
    store.dispatch(
        AssistantRemoveGenericLLMProviderAction(
            provider_id=HERMES_LLM_PROVIDER_ID,
        ),
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
        # Persistent, image-independent state dirs (idempotent — never clobbers
        # data preserved across a delete/reinstall).
        (HERMES_DATA_PATH / 'data').mkdir(exist_ok=True, parents=True)
        (HERMES_DATA_PATH / 'workspace').mkdir(exist_ok=True, parents=True)

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

        _register_assistant_provider(_get_or_create_api_server_key())

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
    cleanup=_cleanup_hermes,
    is_composition=True,
    category='AI Agents',
    secret_keys=(
        HERMES_API_SERVER_KEY_SECRET,
        *HERMES_LLM_PROVIDER_SECRET_KEYS,
    ),
    ports={
        f'{HERMES_GATEWAY_PORT}/tcp': HERMES_GATEWAY_PORT,
        f'{HERMES_DASHBOARD_PORT}/tcp': HERMES_DASHBOARD_PORT,
        f'{HERMES_WEBUI_PORT}/tcp': HERMES_WEBUI_PORT,
    },
)
