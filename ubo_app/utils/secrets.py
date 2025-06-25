"""Module to manage secrets in a .env file."""

from __future__ import annotations

import os

import dotenv

from ubo_app.constants import SECRETS_PATH

SECRETS_PATH.touch(mode=0o600, exist_ok=True)

uid = os.getuid()
gid = os.getgid()
os.chown(SECRETS_PATH, uid, gid)

SECRETS_PATH.chmod(0o600)


def write_secret(*, key: str, value: str) -> None:
    """Write a key-value pair to the secrets environment variables file."""
    dotenv.set_key(
        dotenv_path=SECRETS_PATH,
        key_to_set=key,
        value_to_set=value,
    )


def read_secret(key: str) -> str | None:
    """Read a key-value pair from the secrets environment variables file."""
    return dotenv.get_key(
        dotenv_path=SECRETS_PATH,
        key_to_get=key,
    )


def read_covered_secret(key: str) -> str | None:
    """Read a key-value pair from the secrets environment variables file."""
    value = read_secret(key)
    if value:
        return f'***{value[-4:]}'
    return '<Not set>'


def clear_secret(key: str) -> None:
    """Clear a key-value pair from the secrets environment variables file."""
    dotenv.unset_key(
        dotenv_path=SECRETS_PATH,
        key_to_unset=key,
    )
