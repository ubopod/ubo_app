"""Set up a hotspot on the UBO."""

import subprocess

from ubo_app.logger import get_logger

logger = get_logger('system-manager')


def _start() -> str:
    logger.info('Starting the hotspot')
    try:
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'start', 'ubo-hotspot'],
            check=True,
        )
    except subprocess.CalledProcessError:
        logger.exception('Failed to start the hotspot properly, stopping it...')
        _stop()
        return 'failed'
    else:
        logger.info('Hotspot started')
        return 'done'


def _stop() -> str:
    logger.info('Stopping the hotspot')
    try:
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'stop', 'ubo-hotspot'],
            check=False,
        )
    except subprocess.CalledProcessError:
        logger.exception('Failed to stop the hotspot properly')
        return 'failed'
    else:
        logger.info('Hotspot stopped')
        return 'done'


def hotspot_handler(desired_state: str) -> str:
    """Set up a hotspot on the UBO."""
    if desired_state == 'start':
        return _start()
    if desired_state == 'stop':
        return _stop()
    return 'unknown command'
