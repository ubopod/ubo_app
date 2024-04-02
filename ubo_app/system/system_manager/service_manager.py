"""provides a function to interact with system services."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ubo_app.logging import get_logger


def ssh_handler(command: str) -> str | None:
    """Handle ssh commands."""
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
    if command == 'start':
        subprocess.run(
            ['/usr/bin/env', 'systemctl', 'start', 'sshd'],  # noqa: S603
            check=True,
        )
    if command == 'stop':
        subprocess.run(
            ['/usr/bin/env', 'systemctl', 'stop', 'sshd'],  # noqa: S603
            check=True,
        )
    if command == 'enable':
        subprocess.run(
            ['/usr/bin/env', 'systemctl', 'enable', 'sshd'],  # noqa: S603
            check=True,
        )
    if command == 'disable':
        subprocess.run(
            ['/usr/bin/env', 'systemctl', 'disable', 'sshd'],  # noqa: S603
            check=True,
        )
    msg = f'Invalid ssh command "{command}"'
    raise ValueError(msg)


def system_handler(service: str, command: str) -> str | None:
    """Interact with system services."""
    logger = get_logger('system-manager')
    try:
        if service == 'ssh':
            return ssh_handler(command)
        if service == 'lightdm':
            if command == 'start':
                subprocess.run(
                    ['/usr/bin/env', 'systemctl', 'start', 'lightdm'],  # noqa: S603
                    check=True,
                )
            elif command == 'stop':
                subprocess.run(
                    ['/usr/bin/env', 'systemctl', 'stop', 'lightdm'],  # noqa: S603
                    check=True,
                )
            elif command == 'enable':
                subprocess.run(
                    ['/usr/bin/env', 'systemctl', 'enable', 'lightdm'],  # noqa: S603
                    check=True,
                )
            elif command == 'disable':
                subprocess.run(
                    ['/usr/bin/env', 'systemctl', 'disable', 'lightdm'],  # noqa: S603
                    check=True,
                )
    except Exception:
        logger.exception('Failed to handle SSH command.')
    return None