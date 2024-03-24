"""provides a function to install and start Docker on the host machine."""

from __future__ import annotations

import subprocess
from pathlib import Path


def ssh_handler(command: str) -> str | None:
    """Install and start Docker on the host machine."""
    if command == 'create_temporary_ssh_account':
        result = subprocess.run(
            Path(__file__).parent.joinpath('create_temporary_ssh_account.sh'),  # noqa: S603
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        result.check_returncode()
        return result.stdout
    if command == 'clear_all_temporary_accounts':
        subprocess.run(
            Path(__file__).parent.joinpath('clear_all_temporary_accounts.sh'),  # noqa: S603
            check=False,
        )
    return None
