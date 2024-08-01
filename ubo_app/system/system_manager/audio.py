"""handle audio commands."""

from __future__ import annotations

import time
from pathlib import Path

from ubo_app.logging import get_logger

DEVICE = '1-001a'
DRIVER_PATH = Path('/sys/bus/i2c/drivers/wm8960')


logger = get_logger('system-manager')


def audio_handler(command: str) -> str | None:
    """Install and start Docker on the host machine."""
    if command == 'failure_report':
        logger.info('Audio failure report received, rebinding device...')
        try:
            (DRIVER_PATH / 'unbind').write_text(DEVICE)
            time.sleep(1)
            (DRIVER_PATH / 'bind').write_text(DEVICE)
        except Exception as e:
            logger.exception('Error rebinding device', exc_info=e)
            return 'error'
        else:
            logger.info('Device has been rebound.')
            return 'done'
    return None
