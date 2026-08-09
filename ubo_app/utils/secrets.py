"""Module to manage secrets in a .env file."""

from __future__ import annotations

import functools
import logging
import os
import time

import dotenv

from ubo_app.constants import SECRETS_PATH

SECRETS_PATH.touch(mode=0o600, exist_ok=True)

uid = os.getuid()
gid = os.getgid()
os.chown(SECRETS_PATH, uid, gid)

SECRETS_PATH.chmod(0o600)

# `dotenv.get_key` warns once per missing key. Reading a non-existent secret
# is a normal, expected condition for us (e.g. probing whether a provider has
# been configured), so silence that specific logger to avoid spamming the
# console.
logging.getLogger('dotenv.main').setLevel(logging.ERROR)


@functools.lru_cache(maxsize=1)
def _modification_time_at(_second: int) -> float:
    """Stat the secrets file at most once per distinct ``_second``."""
    return SECRETS_PATH.stat().st_mtime if SECRETS_PATH.exists() else 0


def modification_time() -> float:
    """Return the modification time of the secrets file.

    Callers use this as an autorun *selector* — "re-run when the secrets file
    changes" — which means it is evaluated on every store dispatch, once per
    autorun that depends on it. Statting the file there made the file system,
    rather than the store, the cost of dispatching an action.

    One-second buckets keep the semantics (a secret edited outside the app is
    still noticed, and the value only *changes* when the file does, so nothing
    downstream re-fires spuriously) while collapsing the syscalls to at most
    one a second across every caller.
    """
    return _modification_time_at(int(time.monotonic()))


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


def list_secrets() -> list[str]:
    """Return the names of every secret currently stored."""
    return [key for key in dotenv.dotenv_values(SECRETS_PATH) if key]
