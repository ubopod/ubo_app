"""provides a function to interact with system services."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ubo_app.logging import get_logger


def ssh_handler(command: str) -> str | None:
    """Handle ssh commands."""
    if command == 'create_temporary_ssh_account':
        result = subprocess.run(  # noqa: S603
            Path(__file__).parent.joinpath('create_temporary_ssh_account.sh'),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        result.check_returncode()
        return result.stdout

    if command == 'clear_all_temporary_accounts':
        subprocess.run(  # noqa: S603
            Path(__file__).parent.joinpath('clear_all_temporary_accounts.sh'),
            check=False,
        )
    elif command == 'start':
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'start', 'ssh'],
            check=True,
        )
    elif command == 'stop':
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'stop', 'ssh'],
            check=True,
        )
    elif command == 'enable':
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'enable', 'ssh'],
            check=True,
        )
    elif command == 'disable':
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'disable', 'ssh'],
            check=True,
        )
    else:
        msg = f'Invalid ssh command "{command}"'
        raise ValueError(msg)
    return 'done'


def lightdm_handler(command: str) -> str | None:
    """Handle LightDM commands."""
    if command == 'start':
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'start', 'lightdm'],
            check=True,
        )
    elif command == 'stop':
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'stop', 'lightdm'],
            check=True,
        )
    elif command == 'enable':
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'enable', 'lightdm'],
            check=True,
        )
    elif command == 'disable':
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'disable', 'lightdm'],
            check=True,
        )
    else:
        msg = f'Invalid LightDM command "{command}"'
        raise ValueError(msg)
    return 'done'


def service_handler(service: str, command: str) -> str | None:
    """Interact with system services."""
    logger = get_logger('system-manager')
    if service == 'ssh':
        try:
            return ssh_handler(command)
        except Exception:
            logger.exception('Failed to handle SSH command.')
    if service == 'lightdm':
        try:
            return lightdm_handler(command)
        except Exception:
            logger.exception('Failed to handle LightDM command.')
    return None
