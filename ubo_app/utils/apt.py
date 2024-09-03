"""Utility functions for interacting with the APT package manager."""

from __future__ import annotations

import asyncio
import subprocess

from ubo_app.logging import logger


def install_package(packages: str | list[str], /, *, force: bool = False) -> None:
    """Install a package using the APT package manager."""
    import apt  # pyright: ignore [reportMissingModuleSource]

    package_names = packages if isinstance(packages, list) else [packages]

    cache = apt.Cache()
    logger.info('Installing packages...', extra={'packages': package_names})
    for package_name in package_names:
        if package_name in cache:
            pkg = cache[package_name]
            if not pkg.is_installed or force:
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
    logger.info('Uninstalling package...', extra={'package': package_name})
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


async def is_package_installed(package_name: str) -> bool:
    """Asynchronously check if a package is installed using the APT package manager."""
    try:
        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'dpkg-query',
            '-W',
            '-f=${Status}',
            package_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
    except subprocess.SubprocessError:
        return False
    else:
        return b'install ok installed' in stdout
