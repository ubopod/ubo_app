"""provides a function to interact with system services."""

from __future__ import annotations

import subprocess

from ubo_app.logging import get_logger


def service_handler(service: str, command: str) -> str | None:
    """Interact with system services."""
    logger = get_logger('system-manager')
    if service in ('ssh', 'lightdm'):
        try:
            if command == 'start':
                subprocess.run(  # noqa: S603
                    ['/usr/bin/env', 'systemctl', 'start', service],
                    check=True,
                )
            elif command == 'stop':
                subprocess.run(  # noqa: S603
                    ['/usr/bin/env', 'systemctl', 'stop', service],
                    check=True,
                )
            elif command == 'enable':
                subprocess.run(  # noqa: S603
                    ['/usr/bin/env', 'systemctl', 'enable', service],
                    check=True,
                )
            elif command == 'disable':
                subprocess.run(  # noqa: S603
                    ['/usr/bin/env', 'systemctl', 'disable', service],
                    check=True,
                )
        except Exception:
            logger.exception('Failed to handle service command.')
        else:
            return 'done'
    return None
