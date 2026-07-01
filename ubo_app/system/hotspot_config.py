"""Set up the hotspot configuration files."""

import pathlib
import subprocess
import sys

from ubo_app.constants import WEB_UI_HOTSPOT_PASSWORD
from ubo_app.utils.pod_id import get_pod_id
from ubo_app.utils.template_files import copy_templates, restore_backups

_MODE_FILE = pathlib.Path('/run/ubo-hotspot-mode')
_HOTSPOT_SUBNET = '192.168.4.0/24'
_NAT_CHAIN = 'UBO_HOTSPOT'
_FORWARD_CHAIN = 'UBO_HOTSPOT_FWD'


def _read_mode() -> str:
    """Read the requested hotspot mode (written by the system manager)."""
    try:
        mode = _MODE_FILE.read_text().strip()
    except OSError:
        return 'captive'
    return mode if mode in ('captive', 'share') else 'captive'


def _detect_uplink() -> str | None:
    """Return the non-wlan0 interface that carries a default route, if any."""
    result = subprocess.run(
        ['/usr/bin/env', 'ip', 'route', 'show', 'default'],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        if 'dev' in parts:
            interface = parts[parts.index('dev') + 1]
            if interface != 'wlan0':
                return interface
    return None


def _iptables(*args: str, table: str = 'filter') -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ['/usr/bin/env', 'iptables', '-t', table, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _ensure_linked_chain(table: str, chain: str, parent: str) -> None:
    """Create/flush our chain and jump to it from the TOP of ``parent``.

    The jump must be first: Docker sets the FORWARD policy to DROP and its
    chains run before any appended rule, so hotspot client traffic would be
    dropped before reaching our ACCEPT rules. Inserting first (and removing any
    stale jump) makes our rules win; non-matching traffic RETURNs to Docker.
    """
    _iptables('-N', chain, table=table)  # no-op (non-zero) if it already exists
    _iptables('-F', chain, table=table)
    while _iptables('-C', parent, '-j', chain, table=table).returncode == 0:
        _iptables('-D', parent, '-j', chain, table=table)
    _iptables('-I', parent, '1', '-j', chain, table=table)


def _setup_share_nat(uplink: str) -> None:
    """NAT hotspot clients out to ``uplink`` using dedicated chains.

    Dedicated chains let restore flush exactly our rules without disturbing
    Docker's MASQUERADE rules that share the same tables.
    """
    pathlib.Path('/proc/sys/net/ipv4/ip_forward').write_text('1')
    _ensure_linked_chain('nat', _NAT_CHAIN, 'POSTROUTING')
    _iptables(
        '-A', _NAT_CHAIN,
        '-s', _HOTSPOT_SUBNET, '-o', uplink, '-j', 'MASQUERADE',
        table='nat',
    )
    _ensure_linked_chain('filter', _FORWARD_CHAIN, 'FORWARD')
    _iptables(
        '-A', _FORWARD_CHAIN,
        '-i', 'wlan0', '-o', uplink, '-j', 'ACCEPT',
    )
    _iptables(
        '-A', _FORWARD_CHAIN,
        '-i', uplink, '-o', 'wlan0',
        '-m', 'state', '--state', 'RELATED,ESTABLISHED', '-j', 'ACCEPT',
    )


def _teardown_share_nat() -> None:
    """Flush our NAT/forward rules (chains + jumps stay, harmless when empty)."""
    _iptables('-F', _NAT_CHAIN, table='nat')
    _iptables('-F', _FORWARD_CHAIN, table='filter')


def _write_share_dnsmasq() -> None:
    """Share-mode dnsmasq: DHCP + upstream DNS forwarding (no captive hijack).

    The hotspot's dhcpcd clobbers ``/etc/resolv.conf`` (no nameservers), so we
    can't forward to it - point dnsmasq at explicit public resolvers instead.
    """
    pathlib.Path('/etc/dnsmasq.conf').write_text(
        'interface=wlan0\n'
        'dhcp-range=192.168.4.10,192.168.4.100,255.255.255.0,24h\n'
        'dhcp-option=6,192.168.4.1\n'
        'no-resolv\n'
        'server=1.1.1.1\n'
        'server=8.8.8.8\n',
    )


def main() -> None:
    """Set up the hotspot configuration files."""
    templates_path = pathlib.Path(__file__).parent / 'hotspot_templates'
    if sys.argv[1] == 'configure':
        subprocess.run(
            ['/usr/bin/env', 'iw', 'wlan0', 'set', 'power_save', 'off'],
            check=True,
        )
        subprocess.run(['/usr/bin/env', 'rfkill', 'unblock', 'wifi'], check=True)

        # Release wlan0 from NetworkManager so hostapd can bind it. Without this,
        # toggling the hotspot ON while wlan0 is associated as a station does
        # nothing (NM/wpa_supplicant still hold the interface). check=False so the
        # already-working offline path is never regressed if nmcli differs.
        subprocess.run(
            ['/usr/bin/env', 'nmcli', 'device', 'set', 'wlan0', 'managed', 'no'],
            check=False,
        )

        # 'share' needs a non-wlan0 uplink to NAT out of; fall back to captive.
        mode = _read_mode()
        uplink = _detect_uplink() if mode == 'share' else None
        if mode == 'share' and uplink is None:
            mode = 'captive'

        copy_templates(
            templates_path,
            variables={
                'SSID': get_pod_id(with_default=True),
                'PASSWORD': WEB_UI_HOTSPOT_PASSWORD,
            },
        )

        if mode == 'share' and uplink is not None:
            _write_share_dnsmasq()
            _setup_share_nat(uplink)

        subprocess.run(['/bin/systemctl', 'enable', 'dhcpcd.service'], check=True)
        subprocess.run(['/bin/systemctl', 'restart', 'dhcpcd.service'], check=True)
        subprocess.run(['/bin/systemctl', 'enable', 'dnsmasq.service'], check=True)
        subprocess.run(['/bin/systemctl', 'restart', 'dnsmasq.service'], check=True)
        subprocess.run(['/bin/systemctl', 'unmask', 'hostapd.service'], check=True)
        subprocess.run(['/bin/systemctl', 'enable', 'hostapd.service'], check=True)
        # ``restart`` (not ``start``): a re-configure restarts dhcpcd above,
        # which cycles wlan0 and tears the AP off the radio. ``start`` is a
        # no-op when hostapd is already running, leaving a stale hostapd whose
        # AP is down (interface reverts to managed mode) — so the SSID silently
        # stops broadcasting. ``restart`` rebinds the freshly-configured wlan0.
        subprocess.run(['/bin/systemctl', 'restart', 'hostapd.service'], check=True)
    elif sys.argv[1] == 'restore':
        restore_backups(templates_path)

        # Remove our share-mode NAT (no-op when the hotspot was captive).
        _teardown_share_nat()

        with pathlib.Path('/etc/dhcpcd.conf').open('w') as file:
            file.write(
                '# Default dhcpcd configuration\n'
                '# Leave this blank for automatic configuration\n',
            )

        subprocess.run(['/bin/systemctl', 'stop', 'dhcpcd.service'], check=True)
        subprocess.run(['/bin/systemctl', 'disable', 'dhcpcd.service'], check=True)
        subprocess.run(['/bin/systemctl', 'stop', 'hostapd.service'], check=True)
        subprocess.run(['/bin/systemctl', 'disable', 'hostapd.service'], check=True)
        subprocess.run(['/bin/systemctl', 'mask', 'hostapd.service'], check=True)
        subprocess.run(['/bin/systemctl', 'stop', 'dnsmasq.service'], check=True)
        subprocess.run(['/bin/systemctl', 'disable', 'dnsmasq.service'], check=True)
        # Hand wlan0 back to NetworkManager so it re-manages the radio and
        # autoconnects a remembered, in-range network.
        subprocess.run(
            ['/usr/bin/env', 'nmcli', 'device', 'set', 'wlan0', 'managed', 'yes'],
            check=False,
        )
        subprocess.run(['/usr/bin/env', 'nmcli', 'radio', 'wifi', 'on'], check=True)
        # Belt-and-suspenders: re-apply eth0's connection so its IPv4/route is
        # restored if dhcpcd flushed it on stop (check=False - eth0 may be absent
        # or already healthy, which must not fail the restore).
        subprocess.run(
            ['/usr/bin/env', 'nmcli', 'device', 'reapply', 'eth0'],
            check=False,
        )
    else:
        msg = 'Invalid argument'
        raise ValueError(msg)
