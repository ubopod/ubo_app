"""Installed versions of ubo."""

from __future__ import annotations

from pathlib import Path

from ubo_app.constants import INSTALLATION_PATH


def get_installed_versions() -> list[Path]:
    """Get a list of installed versions of ubo."""
    return [
        item
        for item in Path(INSTALLATION_PATH).iterdir()
        if item.is_dir()
        and not item.is_symlink()
        and (item / 'bin' / 'activate').is_file()
    ]
