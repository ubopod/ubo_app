"""Docker composition presets for one-click installation."""

from __future__ import annotations

import os
from dataclasses import field
from typing import TYPE_CHECKING, Literal

from immutable import Immutable

if TYPE_CHECKING:
    from collections.abc import Callable


class CredentialConfig(Immutable):
    """Configuration for auto-generated credentials."""

    type: Literal['password', 'username', 'token', 'uuid']
    length: int = 32  # For password/token
    charset: Literal['alphanumeric', 'alpha', 'numeric', 'hex'] = 'alphanumeric'
    secret_key: str  # Key to store in .secrets.env
    env_var: str  # Variable name in .env file


class PresetCompositionEntry(Immutable):
    """Preset docker-compose application entry."""

    id: str  # e.g., 'immich'
    label: str  # Display name
    icon: str  # Nerd font icon
    compose_url: str  # URL to docker-compose.yml
    env_url: str | None = None  # URL to .env example file
    instructions: str | None = None  # Setup instructions

    # Credential generation configuration
    credentials: dict[str, CredentialConfig] = field(default_factory=dict)

    # Environment variable template mappings
    env_mappings: dict[str, str | Callable[[], str]] = field(default_factory=dict)

    # Path replacements: relative path -> directory name
    # e.g., {'./library': 'library', './postgres': 'postgres'}
    # Relative paths will be converted to absolute paths within composition directory
    path_replacements: dict[str, str] = field(default_factory=dict)

    # Additional files to download
    additional_files: dict[str, str] = field(default_factory=dict)  # filename -> url


# Immich Preset Configuration
IMMICH_PRESET = PresetCompositionEntry(
    id='immich',
    label='Immich',
    icon='',
    compose_url='https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml',
    env_url='https://github.com/immich-app/immich/releases/latest/download/example.env',
    instructions="""Immich is installed and running!

Access the web interface at:
http://{{hostname}}:2283

On first visit, create an admin account to start uploading your photos and videos.

Default locations:
- Upload directory: ./library
- Database directory: ./postgres

The database credentials have been automatically generated and stored securely.""",
    credentials={
        'db_password': CredentialConfig(
            type='password',
            length=32,
            charset='alphanumeric',
            secret_key='IMMICH_DB_PASSWORD',  # noqa: S106
            env_var='DB_PASSWORD',
        ),
        'db_username': CredentialConfig(
            type='username',
            length=16,
            charset='alphanumeric',
            secret_key='IMMICH_DB_USERNAME',  # noqa: S106
            env_var='DB_USERNAME',
        ),
    },
    env_mappings={
        'IMMICH_VERSION': 'release',
        'DB_DATABASE_NAME': 'immich',
        'TZ': lambda: os.environ.get('TZ', 'UTC'),
    },
    path_replacements={
        './library': 'library',
        './postgres': 'postgres',
    },
)


# Registry of all preset compositions
PRESET_COMPOSITIONS: dict[str, PresetCompositionEntry] = {
    'immich': IMMICH_PRESET,
    # Future presets can be added here:
    # 'nextcloud': NEXTCLOUD_PRESET,  # noqa: ERA001
    # 'jellyfin': JELLYFIN_PRESET, # noqa: ERA001
}
