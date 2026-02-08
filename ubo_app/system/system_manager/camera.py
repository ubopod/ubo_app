"""Handle camera commands."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ubo_app.logger import get_logger

logger = get_logger('system-manager')


def camera_handler(command: str, *args: str) -> str | None:
    """Handle camera commands."""
    if command == 'install_driver':
        make, model, variant = args[0], args[1], args[2]
        if make == 'arducam' and model == 'imx519':
            try:
                script = (
                    Path(__file__).parent.parent
                    / 'scripts/install_arducam_imx519.sh'
                ).read_bytes()
                process = subprocess.run(  # noqa: S603
                    ['/bin/bash', '-s', '--', variant],
                    input=script,
                    check=True,
                )
                process.check_returncode()
            except Exception:
                logger.exception('Error installing Arducam IMX519 driver')
                return 'error'
            else:
                return 'installed'
        logger.error(
            'Unknown camera driver: %s %s',
            make,
            model,
        )
        return 'error'
    if command == 'restore_default':
        try:
            script = (
                Path(__file__).parent.parent
                / 'scripts/restore_default_camera.sh'
            ).read_bytes()
            process = subprocess.run(  # noqa: S603
                ['/bin/bash', '-s'],
                input=script,
                check=True,
            )
            process.check_returncode()
        except Exception:
            logger.exception('Error restoring default camera configuration')
            return 'error'
        else:
            return 'restored'
    return None
