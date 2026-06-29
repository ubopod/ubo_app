"""Set up a hotspot on the UBO."""

import pathlib
import subprocess

from ubo_app.logger import get_logger

logger = get_logger('system-manager')

# The hotspot's networking mode is handed to the systemd ExecStartPre
# (`ubo-hotspot-config configure`) via this file so it survives auto-restart.
_MODE_FILE = pathlib.Path('/run/ubo-hotspot-mode')
_VALID_MODES = ('captive', 'share')


def _start(mode: str) -> str:
    if mode not in _VALID_MODES:
        mode = 'captive'
    logger.info('Starting the hotspot', extra={'mode': mode})
    try:
        _MODE_FILE.write_text(mode)
        subprocess.run(
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
        subprocess.run(
            ['/usr/bin/env', 'systemctl', 'stop', 'ubo-hotspot'],
            check=False,
        )
    except subprocess.CalledProcessError:
        logger.exception('Failed to stop the hotspot properly')
        return 'failed'
    else:
        logger.info('Hotspot stopped')
        return 'done'


def hotspot_handler(desired_state: str, mode: str = 'captive') -> str:
    """Set up a hotspot on the UBO."""
    if desired_state == 'start':
        return _start(mode)
    if desired_state == 'stop':
        return _stop()
    return 'unknown command'
