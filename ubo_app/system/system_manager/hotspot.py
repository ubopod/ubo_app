"""Set up a hotspot on the UBO."""

import asyncio
import pathlib
import subprocess

from ubo_app.system.system_manager.hotspot_server import (
    start_redirect_server,
    stop_redirect_server,
)
from ubo_app.utils.pod_id import get_pod_id
from ubo_app.utils.template_files import copy_templates, restore_backups


def _start() -> None:
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
            check=False,
        )
    except subprocess.CalledProcessError:
        _stop()
    else:
        asyncio.run(start_redirect_server())


def _stop() -> None:
    stop_redirect_server()
    templates_path = pathlib.Path(__file__).parent / 'hotspot_templates'
    restore_backups(templates_path)
    subprocess.run(['/usr/bin/env', 'systemctl', 'stop', 'hostapd'], check=False)  # noqa: S603
    subprocess.run(['/usr/bin/env', 'systemctl', 'disable', 'hostapd'], check=False)  # noqa: S603
    subprocess.run(['/usr/bin/env', 'systemctl', 'mask', 'hostapd'], check=True)  # noqa: S603
    subprocess.run(['/usr/bin/env', 'systemctl', 'stop', 'dnsmasq'], check=False)  # noqa: S603
    subprocess.run(['/usr/bin/env', 'systemctl', 'restart', 'dhcpcd'], check=False)  # noqa: S603


def hotspot_handler(desired_state: str) -> None:
    """Set up a hotspot on the UBO."""
    if desired_state == 'start':
        _start()
    elif desired_state == 'stop':
        _stop()
