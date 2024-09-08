"""Provides the package handler for the system manager."""

from __future__ import annotations

import subprocess

from ubo_app.logging import get_logger
from ubo_app.utils.apt import install_package, uninstall_package

PACKAGE_WHITELIST = [
    'lightdm',
    'rpi-connect',
]

logger = get_logger('system-manager')


def package_handler(action: str, package: str) -> str:
    """Handle package actions."""
    if package not in PACKAGE_WHITELIST:
        return 'Package not in whitelist'

    try:
        if action == 'install':
            if package == 'lightdm':
                install_package('raspberrypi-ui-mods', force=True)
                subprocess.run(  # noqa: S603
                    [
                        '/usr/bin/env',
                        'sed',
                        '-i',
                        '/etc/lightdm/lightdm.conf',
                        '-e',
                        's|#\\?autologin-user=.*|autologin-user=ubo|',
                    ],
                    check=False,
                )
                subprocess.run(  # noqa: S603
                    [
                        '/usr/bin/env',
                        'raspi-config',
                        'nonint',
                        'do_wayland',
                        'W2',
                    ],
                    check=False,
                )
            else:
                install_package(package)
            return 'installed'
        if action == 'uninstall':
            uninstall_package(package)
            return 'uninstalled'
    except Exception:
        logger.exception('Failed to handle package action')
        return 'error'
    else:
        return 'Invalid package action'
