"""Provides the Tailscale handler for the system manager."""

from __future__ import annotations

import subprocess

from ubo_app.constants import USERNAME
from ubo_app.logger import get_logger

logger = get_logger('system-manager')

INSTALL_SCRIPT_URL = 'https://tailscale.com/install.sh'


def tailscale_handler(action: str) -> str:
    """Handle Tailscale actions that require root privileges."""
    try:
        if action == 'install':
            # Tailscale is not in the base apt repositories; the official install
            # script adds Tailscale's apt repository, installs the package and
            # enables the `tailscaled` service.
            script = subprocess.run(  # noqa: S603
                ['/usr/bin/env', 'curl', '-fsSL', INSTALL_SCRIPT_URL],
                check=True,
                capture_output=True,
            ).stdout
            subprocess.run(['/usr/bin/env', 'sh'], input=script, check=True)
            # Allow the unprivileged `ubo` user to control tailscaled without sudo.
            subprocess.run(  # noqa: S603
                ['/usr/bin/env', 'tailscale', 'set', '--operator', USERNAME],
                check=True,
            )
            return 'installed'
        if action == 'uninstall':
            subprocess.run(
                ['/usr/bin/env', 'tailscale', 'down'],
                check=False,
            )
            subprocess.run(
                ['/usr/bin/env', 'apt-get', 'purge', '-y', 'tailscale'],
                check=True,
            )
            return 'uninstalled'
    except Exception:
        logger.exception('Failed to handle Tailscale action')
        return 'error'
    else:
        return 'Invalid Tailscale action'
