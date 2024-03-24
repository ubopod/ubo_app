"""provides a function to install and start Docker on the host machine."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ubo_app.constants import DOCKER_INSTALLATION_LOCK_FILE, USERNAME


def docker_handler(command: str) -> None:
    """Install and start Docker on the host machine."""
    Path.touch(
        DOCKER_INSTALLATION_LOCK_FILE,
        mode=0o666,
        exist_ok=True,
    )
    try:
        if command == 'install':
            subprocess.run(
                Path(__file__).parent.parent.joinpath('install_docker.sh'),  # noqa: S603
                env={'USERNAME': USERNAME},
                check=False,
            )
        elif command == 'start':
            subprocess.run(
                [  # noqa: S603
                    '/usr/bin/env',
                    'systemctl',
                    'start',
                    'docker.socket',
                ],
                check=False,
            )
            subprocess.run(
                [  # noqa: S603
                    '/usr/bin/env',
                    'systemctl',
                    'start',
                    'docker.service',
                ],
                check=False,
            )
        elif command == 'stop':
            subprocess.run(
                [  # noqa: S603
                    '/usr/bin/env',
                    'systemctl',
                    'stop',
                    'docker.socket',
                ],
                check=False,
            )
            subprocess.run(
                [  # noqa: S603
                    '/usr/bin/env',
                    'systemctl',
                    'stop',
                    'docker.service',
                ],
                check=False,
            )
    finally:
        DOCKER_INSTALLATION_LOCK_FILE.unlink(missing_ok=True)
