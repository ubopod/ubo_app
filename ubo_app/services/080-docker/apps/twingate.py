"""Twingate VPN connector Docker app."""

from __future__ import annotations

import asyncio

from apps._registry import ContainerEntry
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

TWINGATE_SECRET_KEYS = (
    'TWINGATE_NETWORK',
    'TWINGATE_ACCESS_TOKEN',
    'TWINGATE_REFRESH_TOKEN',
)


def is_twingate_configured() -> bool:
    """Check if all Twingate credentials are stored."""
    return all(secrets.read_secret(key) for key in TWINGATE_SECRET_KEYS)


async def configure_twingate() -> bool:
    """Prompt for Twingate credentials and store them in secrets."""
    try:
        fields = []
        for key, label, hint in (
            ('TWINGATE_NETWORK', 'Network Name', 'e.g. mynetwork'),
            ('TWINGATE_ACCESS_TOKEN', 'Access Token', None),
            ('TWINGATE_REFRESH_TOKEN', 'Refresh Token', None),
        ):
            current = secrets.read_secret(key)
            if current:
                description = f'Current: {secrets.read_covered_secret(key)}'
            else:
                description = hint

            fields.append(
                InputFieldDescription(
                    name=key,
                    label=label,
                    type=InputFieldType.PASSWORD
                    if 'TOKEN' in key
                    else InputFieldType.TEXT,
                    description=description,
                    required=current is None,
                ),
            )

        _, result = await ubo_input(
            prompt='Configure Twingate',
            descriptions=[WebUIInputDescription(fields=fields)],
        )

        if not result:
            return False

        for key in TWINGATE_SECRET_KEYS:
            value = (result.data.get(key, '') or '').strip()
            if value:
                secrets.write_secret(key=key, value=value)
            elif not secrets.read_secret(key):
                return False
    except asyncio.CancelledError:
        return False
    else:
        return True


async def prepare_twingate() -> bool:
    """Prepare Twingate by ensuring credentials are configured."""
    if is_twingate_configured():
        return True
    return await configure_twingate()


def _menu_actions(
    menu_id: str,
    items: list[MenuItemData],
    action_ids: dict[str, list[str]],
) -> None:
    """Add Twingate-specific menu items when credentials are configured."""
    if not is_twingate_configured():
        return

    reconfigure_id = 'docker:reconfigure:twingate'
    action_ids[menu_id].append(reconfigure_id)
    register_action(
        reconfigure_id,
        lambda: create_task(configure_twingate()),
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
    id='twingate',
    label='Twingate',
    icon='󰒄',
    network_mode='host',
    path='twingate/connector:latest',
    registry='docker.io',
    prepare=prepare_twingate,
    menu_actions=_menu_actions,
    secret_keys=TWINGATE_SECRET_KEYS,
    environment_vairables={
        'TWINGATE_NETWORK': lambda: (
            secrets.read_secret('TWINGATE_NETWORK') or ''
        ),
        'TWINGATE_ACCESS_TOKEN': lambda: (
            secrets.read_secret('TWINGATE_ACCESS_TOKEN') or ''
        ),
        'TWINGATE_REFRESH_TOKEN': lambda: (
            secrets.read_secret('TWINGATE_REFRESH_TOKEN') or ''
        ),
    },
)
