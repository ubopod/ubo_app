"""provides a function to install and start Docker on the host machine."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ubo_app.constants import USERNAME


def docker_handler(command: str) -> str | None:
    """Install and start Docker on the host machine."""
    if command == 'install':
        subprocess.run(  # noqa: S603
            Path(__file__).parent.parent.joinpath('install_docker.sh'),
            env={'USERNAME': USERNAME},
            check=False,
        )
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
