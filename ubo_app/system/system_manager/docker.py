"""provides a function to install and start Docker on the host machine."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ubo_app.constants import USERNAME
from ubo_app.logger import get_logger

logger = get_logger('system-manager')


def docker_handler(command: str) -> str | None:
    """Install and start Docker on the host machine."""
    if command == 'install':
        try:
            process = subprocess.run(  # noqa: S603
                Path(__file__).parent.parent / 'scripts/install_docker.sh',
                env={'USERNAME': USERNAME},
                check=True,
            )
            process.check_returncode()
        except Exception:
            logger.exception('Error installing Docker')
            return 'error'
        else:
            return 'installed'

    if command == 'start':
        subprocess.run(  # noqa: S603
            [
                '/usr/bin/env',
                'systemctl',
                'start',
                'docker.socket',
            ],
            check=False,
        )
        subprocess.run(  # noqa: S603
            [
                '/usr/bin/env',
                'systemctl',
                'start',
                'docker.service',
            ],
            check=False,
        )
    elif command == 'stop':
        subprocess.run(  # noqa: S603
            [
                '/usr/bin/env',
                'systemctl',
                'stop',
                'docker.socket',
            ],
            check=False,
        )
        subprocess.run(  # noqa: S603
            [
                '/usr/bin/env',
                'systemctl',
                'stop',
                'docker.service',
            ],
            check=False,
        )
    return 'done'
