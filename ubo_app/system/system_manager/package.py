"""Provides the package handler for the system manager."""

from __future__ import annotations

from ubo_app.utils.apt import install_package, uninstall_package

PACKAGE_WHITELIST = [
    'lightdm',
    'rpi-connect',
]


def package_handler(action: str, package: str) -> str:
    """Handle package actions."""
    if package not in PACKAGE_WHITELIST:
        return 'Package not in whitelist'

    if action == 'install':
        install_package(package)
        return 'installed'
    if action == 'uninstall':
        uninstall_package(package)
        return 'uninstalled'
    return 'Invalid package action'
