"""Provides the package handler for the system manager."""

from __future__ import annotations

import subprocess

from ubo_app.logger import get_logger
from ubo_app.utils.apt import install_package, uninstall_package

PACKAGE_WHITELIST = [
    'lightdm',
    'rpi-connect',
    'kiosk',
]

logger = get_logger('system-manager')


def _install_lightdm() -> None:
    install_package('raspberrypi-ui-mods', force=True)
    subprocess.run(
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
    subprocess.run(
        ['/usr/bin/env', 'raspi-config', 'nonint', 'do_wayland', 'W2'],
        check=False,
    )


def _install_kiosk() -> None:
    # Each package is installed independently so one failure doesn't prevent
    # the others from being tried.
    failures: list[str] = []
    for package_name in ('weston', 'foot'):
        try:
            install_package(package_name, force=True)
        except ValueError:
            failures.append(package_name)

    # Chromium's package name differs across releases; try each until one works.
    for candidate in ('chromium-browser', 'chromium'):
        try:
            install_package(candidate, force=True)
        except ValueError:
            continue
        else:
            break
    else:
        failures.append('chromium')

    if failures:
        msg = f'Failed to install packages: {", ".join(failures)}'
        raise ValueError(msg)


def package_handler(action: str, package: str) -> str:
    """Handle package actions."""
    if package not in PACKAGE_WHITELIST:
        return 'Package not in whitelist'

    try:
        if action == 'install':
            if package == 'lightdm':
                _install_lightdm()
            elif package == 'kiosk':
                _install_kiosk()
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
