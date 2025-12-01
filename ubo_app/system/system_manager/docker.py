"""provides a function to install and start Docker on the host machine."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ubo_app.constants import USERNAME
from ubo_app.logger import get_logger

logger = get_logger('system-manager')


def _delete_composition(*args: str) -> str | None:
    """Delete a Docker composition by path."""
    logger.info(
        'Deleting composition:',
        extra={'composition_path': args[0] if args else 'unknown'},
    )
    # Delete a composition by full path
    if not args:
        logger.error('No composition path provided for deletion')
        return 'error: no composition path provided'

    composition_path = Path(args[0])
    # Security validation: ensure the path is within a docker_compositions directory
    if composition_path.parent.name != 'docker_compositions':
        logger.error(
            'Invalid composition path: not in docker_compositions directory',
            extra={
                'composition_path': str(composition_path),
                'parent': str(composition_path.parent),
            },
        )
        return 'error: path must be within docker_compositions directory'

    # Check if directory exists
    if not composition_path.exists():
        logger.warning(
            'Composition directory does not exist',
            extra={'composition_path': str(composition_path)},
        )
        return 'done'  # Already deleted, return success

    # Delete the directory (Docker containers create root-owned files)
    try:
        subprocess.run(  # noqa: S603
            [
                '/usr/bin/env',
                'rm',
                '-rf',
                str(composition_path),
            ],
            check=True,
        )
        logger.info(
            'Deleted composition',
            extra={'composition_path': str(composition_path)},
        )
    except subprocess.CalledProcessError:
        logger.exception(
            'Failed to delete composition',
            extra={'composition_path': str(composition_path)},
        )
        return 'error: failed to delete composition'

    return 'done'


def docker_handler(command: str, *args: str) -> str | None:
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
        subprocess.run(
            [
                '/usr/bin/env',
                'systemctl',
                'start',
                'docker.socket',
            ],
            check=False,
        )
        subprocess.run(
            [
                '/usr/bin/env',
                'systemctl',
                'start',
                'docker.service',
            ],
            check=False,
        )
    elif command == 'stop':
        subprocess.run(
            [
                '/usr/bin/env',
                'systemctl',
                'stop',
                'docker.socket',
            ],
            check=False,
        )
        subprocess.run(
            [
                '/usr/bin/env',
                'systemctl',
                'stop',
                'docker.service',
            ],
            check=False,
        )
    elif command == 'composition_delete':
        return _delete_composition(*args)

    return 'done'
