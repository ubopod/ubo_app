"""Set up the hotspot configuration files."""

import pathlib
import subprocess
import sys

from ubo_app.constants import WEB_UI_HOTSPOT_PASSWORD
from ubo_app.utils.pod_id import get_pod_id
from ubo_app.utils.template_files import copy_templates, restore_backups


def main() -> None:
    """Set up the hotspot configuration files."""
    templates_path = pathlib.Path(__file__).parent / 'hotspot_templates'
    if sys.argv[1] == 'configure':
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'iw', 'wlan0', 'set', 'power_save', 'off'],
            check=True,
        )
        subprocess.run(['/usr/bin/env', 'rfkill', 'unblock', 'wifi'], check=True)  # noqa: S603

        copy_templates(
            templates_path,
            variables={
                'SSID': get_pod_id(with_default=True),
                'PASSWORD': WEB_UI_HOTSPOT_PASSWORD,
            },
        )

        subprocess.run(['/bin/systemctl', 'restart', 'dhcpcd.service'], check=True)  # noqa: S603
        subprocess.run(['/bin/systemctl', 'restart', 'dnsmasq.service'], check=True)  # noqa: S603
        subprocess.run(['/bin/systemctl', 'unmask', 'hostapd.service'], check=True)  # noqa: S603
        subprocess.run(['/bin/systemctl', 'enable', 'hostapd.service'], check=True)  # noqa: S603
        subprocess.run(['/bin/systemctl', 'start', 'hostapd.service'], check=True)  # noqa: S603
    elif sys.argv[1] == 'restore':
        restore_backups(templates_path)

        with pathlib.Path('/etc/dhcpcd.conf').open('w') as file:
            file.write(
                '# Default dhcpcd configuration\n'
                '# Leave this blank for automatic configuration\n',
            )

        subprocess.run(['/bin/systemctl', 'stop', 'hostapd.service'], check=True)  # noqa: S603
        subprocess.run(['/bin/systemctl', 'disable', 'hostapd.service'], check=True)  # noqa: S603
        subprocess.run(['/bin/systemctl', 'mask', 'hostapd.service'], check=True)  # noqa: S603
        subprocess.run(['/bin/systemctl', 'stop', 'dnsmasq.service'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'nmcli', 'radio', 'wifi', 'on'], check=True)  # noqa: S603
    else:
        msg = 'Invalid argument'
        raise ValueError(msg)
