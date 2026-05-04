"""Pangolin site connector Docker composition."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from apps._registry import COMPOSITIONS_PATH, ContainerEntry
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import MenuItemData
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

PANGOLIN_COMPOSITION_ID = 'pangolin'
PANGOLIN_LABEL = 'Pangolin'
PANGOLIN_ICON = ''
PANGOLIN_CLOUD_ENDPOINT = 'https://app.pangolin.net'
PANGOLIN_OTHER_ENDPOINT = 'Other'
PANGOLIN_SECRET_KEYS = (
    'PANGOLIN_ENDPOINT',
    'NEWT_ID',
    'NEWT_SECRET',
)


def _is_pangolin_configured() -> bool:
    """Check whether Pangolin has a compose file and stored credentials."""
    composition_path = COMPOSITIONS_PATH / PANGOLIN_COMPOSITION_ID
    return (composition_path / 'docker-compose.yml').exists() and all(
        secrets.read_secret(key) for key in PANGOLIN_SECRET_KEYS
    )


def _build_pangolin_fields() -> list[InputFieldDescription]:
    """Build the web UI form fields for Pangolin site credentials."""
    return [
        InputFieldDescription(
            name='PANGOLIN_ENDPOINT_MODE',
            label='Pangolin endpoint',
            type=InputFieldType.SELECT,
            default_value=PANGOLIN_CLOUD_ENDPOINT,
            options=[PANGOLIN_CLOUD_ENDPOINT, PANGOLIN_OTHER_ENDPOINT],
            required=True,
        ),
        InputFieldDescription(
            name='PANGOLIN_ENDPOINT_OTHER',
            label='Other endpoint',
            type=InputFieldType.TEXT,
            description='Only used when endpoint is set to Other.',
            required=False,
        ),
        InputFieldDescription(
            name='NEWT_ID',
            label='Newt ID',
            type=InputFieldType.TEXT,
            required=True,
        ),
        InputFieldDescription(
            name='NEWT_SECRET',
            label='Newt Secret',
            type=InputFieldType.PASSWORD,
            required=True,
        ),
    ]


def _resolve_endpoint(data: Mapping[str, str]) -> str | None:
    endpoint_mode = (
        data.get('PANGOLIN_ENDPOINT_MODE') or PANGOLIN_CLOUD_ENDPOINT
    ).strip()
    if endpoint_mode == PANGOLIN_OTHER_ENDPOINT:
        return (data.get('PANGOLIN_ENDPOINT_OTHER') or '').strip() or None
    return endpoint_mode or PANGOLIN_CLOUD_ENDPOINT


async def configure_pangolin() -> dict[str, str] | None:
    """Prompt for Pangolin site credentials and store them as secrets."""
    try:
        _, result = await ubo_input(
            prompt='Configure Pangolin',
            descriptions=[
                WebUIInputDescription(fields=_build_pangolin_fields()),
            ],
        )
    except asyncio.CancelledError:
        return None

    if not result:
        return None

    endpoint = _resolve_endpoint(result.data)
    newt_id = (result.data.get('NEWT_ID') or '').strip()
    newt_secret = (result.data.get('NEWT_SECRET') or '').strip()
    if not endpoint or not newt_id or not newt_secret:
        logger.warning('Pangolin configuration submitted incomplete form data')
        return None

    resolved = {
        'PANGOLIN_ENDPOINT': endpoint,
        'NEWT_ID': newt_id,
        'NEWT_SECRET': newt_secret,
    }
    for key, value in resolved.items():
        secrets.write_secret(key=key, value=value)
    return resolved


def _write_pangolin_compose(
    composition_path: Path,
    *,
    endpoint: str,
    newt_id: str,
    newt_secret: str,
) -> None:
    compose_content = (
        'services:\n'
        '  newt:\n'
        '    image: fosrl/newt\n'
        '    container_name: newt\n'
        '    restart: unless-stopped\n'
        '    environment:\n'
        f'      - PANGOLIN_ENDPOINT={endpoint}\n'
        f'      - NEWT_ID={newt_id}\n'
        f'      - NEWT_SECRET={newt_secret}\n'
    )
    (composition_path / 'docker-compose.yml').write_text(compose_content)


def _write_pangolin_metadata(composition_path: Path) -> None:
    metadata = {
        'label': PANGOLIN_LABEL,
        'icon': PANGOLIN_ICON,
        'instructions': (
            'Pangolin site connector is installed and running.\n\n'
            'This Newt container connects outbound to your Pangolin control '
            'plane using the site credentials entered during setup.'
        ),
        'compose_id': PANGOLIN_COMPOSITION_ID,
    }
    (composition_path / 'metadata.json').write_text(json.dumps(metadata))


def _write_pangolin_files(resolved: Mapping[str, str]) -> None:
    composition_path = COMPOSITIONS_PATH / PANGOLIN_COMPOSITION_ID
    composition_path.mkdir(exist_ok=True, parents=True)
    _write_pangolin_compose(
        composition_path,
        endpoint=resolved['PANGOLIN_ENDPOINT'],
        newt_id=resolved['NEWT_ID'],
        newt_secret=resolved['NEWT_SECRET'],
    )
    _write_pangolin_metadata(composition_path)


async def prepare_pangolin() -> bool:
    """Prepare Pangolin by collecting site credentials and writing compose."""
    try:
        logger.info('Preparing Pangolin composition')
        if _is_pangolin_configured():
            return True

        resolved = await configure_pangolin()
        if resolved is None:
            return False

        _write_pangolin_files(resolved)
    except Exception:
        logger.exception('Failed to prepare Pangolin')
        return False
    else:
        return True


async def reconfigure_pangolin() -> bool:
    """Re-prompt for Pangolin credentials and rewrite the compose file."""
    resolved = await configure_pangolin()
    if resolved is None:
        return False
    _write_pangolin_files(resolved)
    return True


def _menu_actions(
    menu_id: str,
    items: list[MenuItemData],
    action_ids: dict[str, list[str]],
) -> None:
    """Add Pangolin-specific menu items."""
    reconfigure_id = 'docker:reconfigure:pangolin'
    action_ids[menu_id].append(reconfigure_id)
    register_action(
        reconfigure_id,
        lambda: create_task(reconfigure_pangolin()),
    )
    items.append(
        MenuItemData(
            key='reconfigure',
            label='Reconfigure',
            icon='󰒓',
            action_id=reconfigure_id,
        ),
    )


ENTRY = ContainerEntry(
    id=PANGOLIN_COMPOSITION_ID,
    label=PANGOLIN_LABEL,
    icon=PANGOLIN_ICON,
    path='fosrl/newt:latest',
    registry='docker.io',
    prepare=prepare_pangolin,
    is_composition=True,
    category='Remote Access',
    secret_keys=PANGOLIN_SECRET_KEYS,
    menu_actions=_menu_actions,
)
