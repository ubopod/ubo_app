"""OpenClaw personal AI gateway Docker composition."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets as py_secrets
from typing import TYPE_CHECKING

import aiohttp

from apps._helpers import (
    SecretKeyEntry,
    build_provider_fields,
    is_checkbox_on,
    resolve_provider_result,
)
from apps._registry import COMPOSITIONS_PATH, ContainerEntry
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import MenuItemData
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

OPENCLAW_COMPOSITION_ID = 'openclaw'
OPENCLAW_COMPOSE_URL = (
    'https://raw.githubusercontent.com/openclaw/openclaw/main/docker-compose.yml'
)
OPENCLAW_IMAGE_REF = 'ghcr.io/openclaw/openclaw:latest'
OPENCLAW_GATEWAY_PORT = 18789
OPENCLAW_BRIDGE_PORT = 18790
OPENCLAW_GATEWAY_TOKEN_SECRET = 'openclaw_gateway_token'  # noqa: S105

OPENCLAW_PROVIDER_MAP: dict[str, SecretKeyEntry] = {
    'openai': SecretKeyEntry(
        'OpenAI', 'OPENAI_API_KEY', 'openai_api_key', 'openai',
    ),
    'anthropic': SecretKeyEntry(
        'Anthropic', 'ANTHROPIC_API_KEY', 'anthropic_api_key', 'anthropic',
    ),
    'gemini': SecretKeyEntry(
        'Google / Gemini', 'GEMINI_API_KEY', 'google_api_key', 'google',
    ),
    'openrouter': SecretKeyEntry(
        'OpenRouter', 'OPENROUTER_API_KEY', 'openrouter_api_key', 'openrouter',
    ),
    'grok': SecretKeyEntry(
        'Grok (xAI)', 'XAI_API_KEY', 'grok_api_key', 'grok',
    ),
}

OPENCLAW_CHANNEL_MAP: dict[str, SecretKeyEntry] = {
    'telegram': SecretKeyEntry(
        'Telegram', 'TELEGRAM_BOT_TOKEN', 'telegram_bot_token', 'telegram',
    ),
    'discord': SecretKeyEntry(
        'Discord', 'DISCORD_BOT_TOKEN', 'discord_bot_token', 'discord',
    ),
    'slack_bot': SecretKeyEntry(
        'Slack (bot token)', 'SLACK_BOT_TOKEN', 'slack_bot_token', 'slack_bot',
    ),
    'slack_app': SecretKeyEntry(
        'Slack (app token)', 'SLACK_APP_TOKEN', 'slack_app_token', 'slack_app',
    ),
}


# ---------------------------------------------------------------------------
# Configuration flow (three-step webUI)
# ---------------------------------------------------------------------------


def is_openclaw_configured() -> bool:
    """Check whether OpenClaw's composition files have already been written."""
    composition_path = COMPOSITIONS_PATH / OPENCLAW_COMPOSITION_ID
    return (
        (composition_path / 'docker-compose.yml').exists()
        and (composition_path / '.env').exists()
        and (composition_path / 'config' / '.env').exists()
    )


async def _prompt_openclaw_providers() -> list[str] | None:
    """Step 1: which model providers should be configured."""
    provider_fields = [
        InputFieldDescription(
            name=slug,
            label=entry.label,
            type=InputFieldType.CHECKBOX,
            default_value='false',
            required=False,
        )
        for slug, entry in OPENCLAW_PROVIDER_MAP.items()
    ]
    _, result = await ubo_input(
        prompt='OpenClaw — select the AI providers you want to configure',
        descriptions=[WebUIInputDescription(fields=provider_fields)],
    )
    if not result:
        return None
    chosen = [
        slug
        for slug in OPENCLAW_PROVIDER_MAP
        if is_checkbox_on(result.data.get(slug))
    ]
    return chosen or None


async def _prompt_openclaw_keys(
    provider_slugs: list[str],
    *,
    resolved: dict[str, str],
) -> bool:
    """Step 2: collect an API key for each chosen provider."""
    key_fields: list[InputFieldDescription] = []
    for slug in provider_slugs:
        entry = OPENCLAW_PROVIDER_MAP[slug]
        key_fields.extend(
            build_provider_fields(
                slug, entry.label, entry.canonical, entry.match_substring,
                required=True,
            ),
        )
    _, result = await ubo_input(
        prompt='OpenClaw — enter or reuse API keys',
        descriptions=[WebUIInputDescription(fields=key_fields)],
    )
    if not result:
        return False
    for slug in provider_slugs:
        entry = OPENCLAW_PROVIDER_MAP[slug]
        value = resolve_provider_result(result.data, slug, entry.canonical)
        if not value:
            logger.warning(
                'OpenClaw provider submitted without a key',
                extra={'provider': slug},
            )
            return False
        resolved[entry.env_var] = value
    return True


async def _prompt_openclaw_channels(*, resolved: dict[str, str]) -> None:
    """Step 3: optional channel tokens. Skipping is always valid."""
    channel_fields: list[InputFieldDescription] = []
    for slug, entry in OPENCLAW_CHANNEL_MAP.items():
        channel_fields.extend(
            build_provider_fields(
                slug, entry.label, entry.canonical, entry.match_substring,
                required=False,
            ),
        )
    try:
        _, result = await ubo_input(
            prompt='Optional: channel tokens — leave blank to configure these '
            'later in the OpenClaw dashboard',
            descriptions=[WebUIInputDescription(fields=channel_fields)],
        )
    except asyncio.CancelledError:
        return
    if not result:
        return
    for slug, entry in OPENCLAW_CHANNEL_MAP.items():
        value = resolve_provider_result(result.data, slug, entry.canonical)
        if value:
            resolved[entry.env_var] = value


async def configure_openclaw() -> dict[str, str] | None:
    """Run the three-step OpenClaw configuration flow."""
    try:
        providers = await _prompt_openclaw_providers()
        if not providers:
            return None
        resolved: dict[str, str] = {}
        if not await _prompt_openclaw_keys(providers, resolved=resolved):
            return None
        await _prompt_openclaw_channels(resolved=resolved)
    except asyncio.CancelledError:
        return None
    return resolved


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _generate_gateway_token() -> str:
    return py_secrets.token_urlsafe(32)


async def _fetch_openclaw_compose() -> str:
    async with aiohttp.ClientSession() as session, session.get(
        OPENCLAW_COMPOSE_URL,
    ) as response:
        response.raise_for_status()
        return await response.text()


def _write_openclaw_user_env(
    composition_path: Path,
    env_vars: Mapping[str, str],
) -> None:
    (composition_path / 'config').mkdir(exist_ok=True, parents=True)
    lines = [f'{key}={value}' for key, value in env_vars.items()]
    (composition_path / 'config' / '.env').write_text(
        '\n'.join(lines) + ('\n' if lines else ''),
    )


def _build_allowed_origins() -> list[str]:
    """Build the list of origins the OpenClaw dashboard should accept."""
    from ubo_app.utils.pod_id import get_pod_id

    origins = [
        f'http://localhost:{OPENCLAW_GATEWAY_PORT}',
        f'http://127.0.0.1:{OPENCLAW_GATEWAY_PORT}',
    ]
    pod_id = get_pod_id()
    if pod_id:
        origins.append(f'http://{pod_id}.local:{OPENCLAW_GATEWAY_PORT}')
    return origins


def _ensure_openclaw_json_config(composition_path: Path) -> None:
    """Seed or update ``openclaw.json`` with required gateway settings.

    Always ensures ``gateway.mode`` and ``gateway.controlUi.allowedOrigins``
    are set, merging into an existing config if one was already written (e.g.,
    by a previous OpenClaw startup).
    """
    config_dir = composition_path / 'config'
    config_dir.mkdir(exist_ok=True, parents=True)
    config_path = config_dir / 'openclaw.json'

    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            config = {}
    else:
        config = {}

    gateway = config.setdefault('gateway', {})
    gateway.setdefault('mode', 'local')
    control_ui = gateway.setdefault('controlUi', {})
    control_ui['allowedOrigins'] = _build_allowed_origins()

    config_path.write_text(json.dumps(config, indent=2))


def _write_openclaw_docker_env(
    composition_path: Path,
    token: str,
) -> None:
    docker_env = (
        f'OPENCLAW_IMAGE={OPENCLAW_IMAGE_REF}\n'
        f'OPENCLAW_GATEWAY_TOKEN={token}\n'
        f'OPENCLAW_GATEWAY_PORT={OPENCLAW_GATEWAY_PORT}\n'
        f'OPENCLAW_BRIDGE_PORT={OPENCLAW_BRIDGE_PORT}\n'
        f'OPENCLAW_GATEWAY_BIND=lan\n'
        f'OPENCLAW_CONFIG_DIR={composition_path / "config"}\n'
        f'OPENCLAW_WORKSPACE_DIR={composition_path / "workspace"}\n'
        f'OPENCLAW_TZ={os.environ.get("TZ", "UTC")}\n'
    )
    (composition_path / '.env').write_text(docker_env)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def _dispatch_openclaw_notification(token: str) -> None:
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Importance,
        Notification,
        NotificationDisplayType,
        NotificationsAddAction,
    )

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='docker:openclaw:gateway_token',
                title='OpenClaw installed',
                content=(
                    f'Dashboard: http://<device-ip>:{OPENCLAW_GATEWAY_PORT}\n'
                    f'Token: {token}'
                ),
                importance=Importance.MEDIUM,
                icon='󰒍',
                display_type=NotificationDisplayType.STICKY,
                show_dismiss_action=True,
                dismiss_on_close=True,
            ),
        ),
    )


def _dispatch_openclaw_cancelled_notification(reason: str) -> None:
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Importance,
        Notification,
        NotificationsAddAction,
    )

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='OpenClaw not installed',
                content=reason,
                importance=Importance.MEDIUM,
                icon='󰒍',
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Prepare / reconfigure
# ---------------------------------------------------------------------------


async def prepare_openclaw() -> bool:
    """Prepare the OpenClaw composition: collect keys, fetch compose, write files."""
    try:
        composition_path = COMPOSITIONS_PATH / OPENCLAW_COMPOSITION_ID
        logger.info(
            'Preparing OpenClaw composition',
            extra={'composition_path': str(composition_path)},
        )

        if not is_openclaw_configured():
            resolved = await configure_openclaw()
            if resolved is None:
                _dispatch_openclaw_cancelled_notification(
                    'Install cancelled before any API keys were provided. '
                    'Select at least one AI provider and submit to continue.',
                )
                return False
        else:
            resolved = None

        composition_path.mkdir(exist_ok=True, parents=True)
        (composition_path / 'workspace').mkdir(exist_ok=True, parents=True)

        gateway_token = (
            secrets.read_secret(OPENCLAW_GATEWAY_TOKEN_SECRET)
            or _generate_gateway_token()
        )
        secrets.write_secret(
            key=OPENCLAW_GATEWAY_TOKEN_SECRET, value=gateway_token,
        )

        compose_content = await _fetch_openclaw_compose()
        (composition_path / 'docker-compose.yml').write_text(compose_content)

        _write_openclaw_docker_env(composition_path, gateway_token)
        if resolved is not None:
            _write_openclaw_user_env(composition_path, resolved)
        _ensure_openclaw_json_config(composition_path)

        metadata = {
            'label': 'OpenClaw',
            'icon': '󰒍',
            'instructions': (
                'OpenClaw is installed and running!\n\n'
                f'Dashboard: http://{{{{hostname}}}}:{OPENCLAW_GATEWAY_PORT}\n\n'
                'Your gateway token is available from the OpenClaw menu → '
                '"Show gateway token".'
            ),
            'compose_id': OPENCLAW_COMPOSITION_ID,
        }
        (composition_path / 'metadata.json').write_text(json.dumps(metadata))

        _dispatch_openclaw_notification(gateway_token)
    except Exception:
        logger.exception('Failed to prepare OpenClaw')
        return False
    else:
        return True


async def reconfigure_openclaw() -> bool:
    """Re-prompt for keys and rewrite ``config/.env`` only."""
    resolved = await configure_openclaw()
    if resolved is None:
        return False
    _write_openclaw_user_env(
        COMPOSITIONS_PATH / OPENCLAW_COMPOSITION_ID,
        resolved,
    )
    return True


def read_openclaw_token() -> str | None:
    """Return the stored gateway token, if any."""
    return secrets.read_secret(OPENCLAW_GATEWAY_TOKEN_SECRET)


def regenerate_openclaw_token() -> str:
    """Mint a fresh gateway token and update the compose ``.env``."""
    token = _generate_gateway_token()
    secrets.write_secret(key=OPENCLAW_GATEWAY_TOKEN_SECRET, value=token)
    env_path = COMPOSITIONS_PATH / OPENCLAW_COMPOSITION_ID / '.env'
    if env_path.exists():
        lines = env_path.read_text().splitlines()
        replaced = False
        for index, line in enumerate(lines):
            if line.startswith('OPENCLAW_GATEWAY_TOKEN='):
                lines[index] = f'OPENCLAW_GATEWAY_TOKEN={token}'
                replaced = True
                break
        if not replaced:
            lines.append(f'OPENCLAW_GATEWAY_TOKEN={token}')
        env_path.write_text('\n'.join(lines) + '\n')
    return token


# ---------------------------------------------------------------------------
# CLI helpers (device pairing)
# ---------------------------------------------------------------------------


_OPENCLAW_UUID_RE = re.compile(
    r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
    re.IGNORECASE,
)


async def _run_openclaw_cli(*args: str) -> tuple[int, str]:
    composition_path = COMPOSITIONS_PATH / OPENCLAW_COMPOSITION_ID
    if not composition_path.exists():
        return 1, 'OpenClaw is not installed.'
    process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'run',
        '--rm',
        '-T',
        'openclaw-cli',
        *args,
        cwd=composition_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout_bytes, _ = await process.communicate()
    return process.returncode or 0, stdout_bytes.decode('utf-8', errors='replace')


async def approve_openclaw_pairings() -> tuple[int, str]:
    """Approve every pending OpenClaw device-pair request."""
    code, output = await _run_openclaw_cli('devices', 'list')
    if code != 0:
        return 0, f'Failed to list devices:\n{output.strip()[:500]}'

    pending = _OPENCLAW_UUID_RE.findall(output)
    if not pending:
        return 0, (
            'No pending pairing requests. Open the OpenClaw dashboard and '
            'click Connect to create one, then try again.'
        )

    approved: list[str] = []
    failures: list[str] = []
    for uuid in pending:
        approve_code, approve_output = await _run_openclaw_cli(
            'devices', 'approve', uuid,
        )
        if approve_code == 0:
            approved.append(uuid)
        else:
            failures.append(f'{uuid[:8]}…: {approve_output.strip()[:120]}')

    if failures and not approved:
        return 0, 'All approvals failed:\n' + '\n'.join(failures)
    if failures:
        return len(approved), (
            f'Approved {len(approved)} device(s), '
            f'{len(failures)} failed:\n'
            + '\n'.join(failures)
            + '\n\nRefresh the dashboard to continue.'
        )
    return len(approved), (
        f'Approved {len(approved)} device(s). Refresh your dashboard to continue.'
    )


# ---------------------------------------------------------------------------
# Menu hook
# ---------------------------------------------------------------------------


def _menu_actions(
    menu_id: str,
    items: list[MenuItemData],
    action_ids: dict[str, list[str]],
) -> None:
    """Add OpenClaw-specific menu items."""
    from ubo_app.store.main import store
    from ubo_app.store.services.docker import (
        DockerImageRunAction,
        DockerImageStopAction,
    )
    from ubo_app.store.services.notifications import (
        Importance,
        Notification,
        NotificationsAddAction,
    )

    reconfigure_id = 'docker:reconfigure:openclaw'
    action_ids[menu_id].append(reconfigure_id)
    register_action(
        reconfigure_id,
        lambda: create_task(reconfigure_openclaw()),
    )
    items.append(
        MenuItemData(
            key='reconfigure',
            label='Reconfigure',
            icon='󰒓',
            action_id=reconfigure_id,
        ),
    )

    show_token_id = 'docker:openclaw:show_token'  # noqa: S105
    action_ids[menu_id].append(show_token_id)

    def _show_token() -> None:
        token = read_openclaw_token()
        if not token:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='OpenClaw gateway token',
                        content='No token is stored yet. Install OpenClaw first.',
                        icon='󰍛',
                        importance=Importance.LOW,
                    ),
                ),
            )
            return

        def _regenerate() -> None:
            new_token = regenerate_openclaw_token()
            store.dispatch(
                DockerImageStopAction(image='openclaw'),
                DockerImageRunAction(image='openclaw'),
                NotificationsAddAction(
                    notification=Notification(
                        title='OpenClaw token regenerated',
                        content=f'New token: {new_token}',
                        icon='󰒍',
                        importance=Importance.MEDIUM,
                    ),
                ),
            )

        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='docker:openclaw:show_token',
                    title='OpenClaw gateway token',
                    content=f'Token: {token}',
                    icon='󰒍',
                    importance=Importance.MEDIUM,
                    extra_information=ReadableInformation(
                        text='Use this token to authenticate when visiting '
                        'the OpenClaw dashboard. Regenerating invalidates the '
                        'old token and restarts the composition.',
                    ),
                    actions=[
                        create_notification_action(
                            action=_regenerate,
                            icon='󰑐',
                            label='Regenerate',
                        ),
                    ],
                ),
            ),
        )

    register_action(show_token_id, _show_token)
    items.append(
        MenuItemData(
            key='show_token',
            label='Show gateway token',
            icon='󰌋',
            action_id=show_token_id,
        ),
    )

    approve_id = 'docker:openclaw:approve_pairing'
    action_ids[menu_id].append(approve_id)

    def _approve() -> None:
        async def _do() -> None:
            _, message = await approve_openclaw_pairings()
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='OpenClaw pairing',
                        content=message,
                        icon='󰒍',
                        importance=Importance.MEDIUM,
                    ),
                ),
            )

        create_task(_do())

    register_action(approve_id, _approve)
    items.append(
        MenuItemData(
            key='approve_pairing',
            label='Approve pairing',
            icon='󰔂',
            action_id=approve_id,
        ),
    )


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

ENTRY = ContainerEntry(
    id=OPENCLAW_COMPOSITION_ID,
    label='OpenClaw',
    icon='󰒍',
    path='openclaw/openclaw:latest',
    registry='ghcr.io',
    prepare=prepare_openclaw,
    is_composition=True,
    ports={
        f'{OPENCLAW_GATEWAY_PORT}/tcp': OPENCLAW_GATEWAY_PORT,
        f'{OPENCLAW_BRIDGE_PORT}/tcp': OPENCLAW_BRIDGE_PORT,
    },
    secret_keys=(OPENCLAW_GATEWAY_TOKEN_SECRET,),
    menu_actions=_menu_actions,
)
