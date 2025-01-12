"""Set up a hotspot on the UBO."""

import pathlib
import subprocess

from ubo_app.utils.pod_id import get_pod_id


def hotspot_handler(desired_state: str) -> None:
    """Set up a hotspot on the UBO."""
    if desired_state == 'start':
        with pathlib.Path('/etc/dhcpcd.conf').open('w') as f:
            f.write("""interface wlan0
static ip_address=192.168.4.1/24
nohook wpa_supplicant""")
        with pathlib.Path('/etc/dnsmasq.conf').open('w') as f:
            f.write("""interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h""")
        with pathlib.Path('/etc/hostapd/hostapd.conf').open('w') as f:
            f.write(f"""interface=wlan0
driver=nl80211
ssid={get_pod_id()}
hw_mode=g
channel=7
wpa=2
wpa_passphrase=ubo-pod-setup
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP CCMP
rsn_pairwise=CCMP""")
        with pathlib.Path('/etc/default/hostapd').open('w') as f:
            f.write('DAEMON_CONF="/etc/hostapd/hostapd.conf"')

        subprocess.run(['/usr/bin/env', 'systemctl', 'restart', 'dhcpcd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'restart', 'dnsmasq'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'unmask', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'enable', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'start', 'hostapd'], check=True)  # noqa: S603

    elif desired_state == 'stop':
        subprocess.run(['/usr/bin/env', 'systemctl', 'stop', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'disable', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'mask', 'hostapd'], check=True)  # noqa: S603
        subprocess.run(['/usr/bin/env', 'systemctl', 'stop', 'dnsmasq'], check=True)  # noqa: S603
        with pathlib.Path('/etc/dhcpcd.conf').open('w') as f:
            f.write("""# Default dhcpcd configuration
                    # Leave this blank for automatic configuration
                    """)
        subprocess.run(['/usr/bin/env', 'systemctl', 'restart', 'dhcpcd'], check=True)  # noqa: S603
