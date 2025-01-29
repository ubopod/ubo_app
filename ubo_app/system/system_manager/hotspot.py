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


def hotspot_handler(desired_state: str) -> None:
    """Set up a hotspot on the UBO."""
    if desired_state == 'start':
        templates_path = pathlib.Path(__file__).parent / 'hotspot_templates'
        copy_templates(
            templates_path,
            variables={'SSID': get_pod_id(with_default=True)},
        )
        subprocess.run(['/usr/bin/env', 'systemctl', 'restart', 'dhcpcd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'restart', 'dnsmasq'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'unmask', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'enable', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'start', 'hostapd'], check=True)  # noqa: S603
        asyncio.run(start_redirect_server())

    elif desired_state == 'stop':
        stop_redirect_server()
        templates_path = pathlib.Path(__file__).parent / 'hotspot_templates'
        restore_backups(templates_path)
        subprocess.run(['/usr/bin/env', 'systemctl', 'stop', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'disable', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'mask', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'stop', 'dnsmasq'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'restart', 'dhcpcd'], check=True)  # noqa: S603
