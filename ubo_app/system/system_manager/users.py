"""provides a function to interact with system services."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ubo_app.logging import get_logger


def users_handler(command: str, username: str | None = None) -> str | None:
    """Interact with system services."""
    logger = get_logger('system-manager')
    try:
        if command == 'create':
            result = subprocess.run(  # noqa: S603
                Path(__file__).parent / 'scripts' / 'set_account.sh',
                check=False,
                text=True,
                capture_output=True,
                env={},
            )
            if result.returncode != 0:
                logger.error(
                    'Failed to create account.',
                    extra={'output': result.stdout, 'error': result.stderr},
                )
            result.check_returncode()
            return result.stdout
        if command == 'reset_password' and username:
            result = subprocess.run(  # noqa: S603
                Path(__file__).parent / 'scripts' / 'set_account.sh',
                check=False,
                text=True,
                capture_output=True,
                env={'USERNAME': username},
            )
            if result.returncode != 0:
                logger.error(
                    'Failed to reset password.',
                    extra={
                        'username': username,
                        'output': result.stdout,
                        'error': result.stderr,
                    },
                )
            result.check_returncode()
            return result.stdout
        if command == 'delete' and username:
            result = subprocess.run(  # noqa: S603
                Path(__file__).parent / 'scripts' / 'delete_account.sh',
                check=False,
                text=True,
                capture_output=True,
                env={'USERNAME': username},
            )
            if result.returncode != 0:
                logger.error(
                    'Failed to delete account.',
                    extra={
                        'username': username,
                        'output': result.stdout,
                        'error': result.stderr,
                    },
                )
            result.check_returncode()
    except Exception:
        logger.exception('Failed to handle service command.')
    else:
        return 'done'
    return None
