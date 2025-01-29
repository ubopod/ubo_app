"""Set up a hotspot on the UBO."""

import pathlib
import subprocess

from ubo_app.logger import get_logger
from ubo_app.utils.pod_id import get_pod_id
from ubo_app.utils.template_files import copy_templates, restore_backups

logger = get_logger('system-manager')


def _start() -> str:
    logger.info('Starting the hotspot')
    templates_path = pathlib.Path(__file__).parent / 'hotspot_templates'
    copy_templates(
        templates_path,
        variables={'SSID': get_pod_id(with_default=True)},
    )
    try:
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'iw', 'wlan0', 'set', 'power_save', 'off'],
            check=True,
        )
        subprocess.run(['/usr/bin/env', 'rfkill', 'unblock', 'wifi'], check=True)  # noqa: S603
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'restart', 'dhcpcd'],
            check=True,
        )
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'restart', 'dnsmasq'],
            check=True,
        )
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'unmask', 'hostapd'],
            check=True,
        )
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'enable', 'hostapd'],
            check=True,
        )
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'start', 'hostapd'],
            check=True,
        )
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'start', 'ubo-redirect-server'],
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
    templates_path = pathlib.Path(__file__).parent / 'hotspot_templates'
    restore_backups(templates_path)
    try:
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'systemctl', 'stop', 'ubo-redirect-server'],
            check=False,
        )
        subprocess.run(['/usr/bin/env', 'systemctl', 'stop', 'hostapd'], check=False)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'disable', 'hostapd'], check=False)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'mask', 'hostapd'], check=False)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'stop', 'dnsmasq'], check=False)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'restart', 'dhcpcd'], check=False)  # noqa: S603
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
