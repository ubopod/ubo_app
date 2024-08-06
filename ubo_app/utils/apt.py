"""Utility functions for interacting with the APT package manager."""

from __future__ import annotations

import asyncio

from ubo_app.logging import logger


def install_package(package_name: str) -> None:
    """Install a package using the APT package manager."""
    import apt  # pyright: ignore [reportMissingModuleSource]

    cache = apt.Cache()
    logger.debug('Installing package...', extra={'package': package_name})
    if package_name in cache:
        pkg = cache[package_name]
        if not pkg.is_installed:
            pkg.mark_install()
            cache.commit()
            logger.info(
                'Package installed successfully.',
                extra={'package': package_name},
            )
        else:
            msg = f'Package {package_name} is already installed.'
            raise ValueError(msg)
    else:
        msg = f'Package {package_name} not found in APT cache.'
        raise ValueError(msg)


def uninstall_package(package_name: str) -> None:
    """Uninstall a package using the APT package manager."""
    import apt  # pyright: ignore [reportMissingModuleSource]

    cache = apt.Cache()
    logger.debug('Uninstalling package...', extra={'package': package_name})
    if package_name in cache:
        pkg = cache[package_name]
        if pkg.is_installed:
            pkg.mark_delete()
            cache.commit()
            logger.info(
                'Package uninstalled successfully.',
                extra={'package': package_name},
            )
        else:
            msg = f'Package {package_name} is not installed.'
            raise ValueError(msg)
    else:
        msg = f'Package {package_name} not found in APT cache.'
        raise ValueError(msg)


def _is_package_installed(package_name: str) -> bool:
    """Check if a package is installed using the APT package manager."""
    import apt  # pyright: ignore [reportMissingModuleSource]

    cache = apt.Cache()
    if package_name in cache:
        pkg = cache[package_name]
        return pkg.is_installed

    return False


async def is_package_installed(package_name: str) -> bool:
    """Asynchronously check if a package is installed using the APT package manager."""
    return await asyncio.to_thread(_is_package_installed, package_name)
