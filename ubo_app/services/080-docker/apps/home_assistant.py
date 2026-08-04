"""Home Assistant Docker composition.

Home Assistant ships as a Compose-managed stack (rather than a single
container) so it can anchor an add-on ecosystem on the shared `ubo_net`
bridge: a bundled MQTT broker, optional macvlan discovery, and Zigbee USB
passthrough into HA's built-in ZHA all attach to the same project.

The compose file is a *derived artifact* — it is re-rendered from current
intent on every (re)start via `prepare_home_assistant` (called by
`run_composition`), so device mappings and network attachments never get baked
into a stale YAML that could brick an unattended boot.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import re
import secrets
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from apps._registry import COMPOSITIONS_PATH, UBO_NET, ContainerEntry
from ubo_app.constants import CONFIG_PATH
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import (
    MenuItemData,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageRunAction,
    DockerSetMacvlanConfigAction,
    DockerSetZigbeeIntentAction,
)
from ubo_app.store.services.mqtt import (
    BUNDLED_BROKER_PASSWORD_SECRET_ID,
    BUNDLED_BROKER_USERNAME,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.secrets import read_secret, write_secret

if TYPE_CHECKING:
    from ubo_app.store.services.docker import DockerServiceState

HOME_ASSISTANT_COMPOSITION_ID = 'home_assistant'
HOME_ASSISTANT_LABEL = 'Home Assistant'
HOME_ASSISTANT_ICON = '󰟐'
HOME_ASSISTANT_IMAGE = 'homeassistant/home-assistant:stable'

# Stable serial-by-id symlinks for USB coordinators; we map the chosen one to a
# constant in-container path so ZHA's config never depends on a volatile
# `ttyUSBN` index.
SERIAL_BY_ID_PATH = Path('/dev/serial/by-id')
ZIGBEE_CONTAINER_DEVICE = '/dev/ttyUSB0'

# Persistent host directory for Home Assistant state, kept OUTSIDE the
# composition directory so neither `docker compose down -v` nor the
# composition-directory removal on uninstall destroys the user's config (and,
# later, the Zigbee mesh pairings). Mirrors the Hermes data-path precedent.
HOME_ASSISTANT_DATA_PATH = CONFIG_PATH / 'home-assistant'


def _detect_timezone() -> str:
    """Best-effort host timezone for HA's `TZ` env (falls back to UTC)."""
    timezone_file = Path('/etc/timezone')
    if timezone_file.exists():
        timezone = timezone_file.read_text().strip()
        if timezone:
            return timezone
    localtime = Path('/etc/localtime')
    if localtime.is_symlink():
        marker = '/zoneinfo/'
        target = str(localtime.resolve())
        if marker in target:
            return target.split(marker, 1)[1]
    return 'UTC'


def detect_serial_adapters() -> list[str]:
    """Enumerate stable `/dev/serial/by-id` symlinks (no privilege required).

    Returns 0, 1, or many adapter paths so callers can present a chooser when
    more than one coordinator is plugged in.
    """
    if not SERIAL_BY_ID_PATH.is_dir():
        return []
    return sorted(str(path) for path in SERIAL_BY_ID_PATH.iterdir())


@store.with_state(lambda state: state.docker.service)
def _zigbee_intent(service: DockerServiceState) -> tuple[bool, str]:
    """Read the desired Zigbee passthrough intent from the store."""
    return service.zigbee_enabled, service.zigbee_adapter_by_id


def _notify_zigbee_degraded() -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title=HOME_ASSISTANT_LABEL,
                content=(
                    'Zigbee adapter not detected — started without it. '
                    'Re-attach the coordinator from the Home Assistant menu.'
                ),
                display_type=NotificationDisplayType.FLASH,
                icon=HOME_ASSISTANT_ICON,
            ),
        ),
    )


def zigbee_intent_unsatisfied() -> bool:
    """Whether Zigbee passthrough is desired but its adapter is absent.

    Used by the render to decide whether to emit/degrade the `devices:` mapping.
    """
    enabled, adapter_by_id = _zigbee_intent()
    return enabled and (
        not adapter_by_id or adapter_by_id not in detect_serial_adapters()
    )


def zigbee_adapter_went_missing() -> bool:
    """Report a configured Zigbee adapter that is no longer plugged in.

    Stricter than :func:`zigbee_intent_unsatisfied`: it requires that a concrete
    adapter was previously chosen (not merely that passthrough is toggled on).
    The boot-heal uses this so it only recovers HA when a real, configured
    coordinator vanished — the case whose stale `devices:` line would hard-fail
    `up` — rather than restarting an HA the user may have stopped on purpose
    before ever completing Zigbee setup.
    """
    enabled, adapter_by_id = _zigbee_intent()
    return enabled and bool(adapter_by_id) and (
        adapter_by_id not in detect_serial_adapters()
    )


def _resolve_zigbee_device() -> str | None:
    """Resolve the host serial device to map, from intent + live presence.

    - desired off → ``None`` (no mapping).
    - desired on + adapter present → the adapter's stable by-id path.
    - desired on + adapter absent → ``None`` + a degraded notification, so HA
      always boots and the dongle re-attaches on the next start/button press.
    """
    enabled, adapter_by_id = _zigbee_intent()
    if not enabled:
        return None
    if adapter_by_id and adapter_by_id in detect_serial_adapters():
        return adapter_by_id
    _notify_zigbee_degraded()
    return None


# Network-interface names are restricted to this safe character set; the IP /
# subnet / gateway fields are validated as real addresses. This prevents YAML
# injection: every macvlan value is rendered into docker-compose.yml via raw
# string interpolation, so a value containing a newline could otherwise inject
# arbitrary service keys (e.g. `privileged: true`). The store is reachable over
# the unauthenticated gRPC port, so we validate at render time too, not just at
# the input form.
_PARENT_IFACE_RE = re.compile(r'[A-Za-z0-9_.-]+')


def _is_valid_macvlan(config: dict[str, str]) -> bool:
    """Reject any macvlan field that isn't a strict address/interface token.

    Also requires the reserved IP to fall inside the subnet — a mismatch would
    otherwise make `docker compose up` fail with a cryptic daemon error.
    """
    try:
        network = ipaddress.ip_network(config['subnet'], strict=False)
        if ipaddress.ip_address(config['ip']) not in network:
            return False
        ipaddress.ip_address(config['gateway'])
    except ValueError:
        return False
    return bool(_PARENT_IFACE_RE.fullmatch(config['parent']))


@store.with_state(lambda state: state.docker.service)
def _resolve_macvlan(service: DockerServiceState) -> dict[str, str] | None:
    """Resolve the macvlan network config from intent, or None when disabled.

    Returns ``None`` unless macvlan is enabled, all four parameters are present,
    AND they pass validation. An incomplete or malformed config falls back to
    bridge-only rather than bricking `up` or injecting into the compose YAML.
    """
    if not service.macvlan_enabled:
        return None
    config = {
        'parent': service.macvlan_parent,
        'subnet': service.macvlan_subnet,
        'gateway': service.macvlan_gateway,
        'ip': service.macvlan_ip,
    }
    if all(config.values()) and _is_valid_macvlan(config):
        return config
    return None


def parse_lan_params(ip_route: str, ip_addr: str) -> dict[str, str]:
    """Derive macvlan prefills (parent iface, subnet, gateway) from `ip` output.

    Pure parsing of `ip route` (default gateway + parent interface) and
    `ip -o addr` (the interface's CIDR → network address). Returns whatever it
    can determine; callers confirm/override via the web form.
    """
    params: dict[str, str] = {}
    route_match = re.search(
        r'^default via (\S+) dev (\S+)',
        ip_route,
        re.MULTILINE,
    )
    if not route_match:
        return params
    params['gateway'] = route_match.group(1)
    params['parent'] = route_match.group(2)
    addr_match = re.search(
        rf'\b{re.escape(params["parent"])}\b\s+inet\s+(\S+)/(\d+)',
        ip_addr,
    )
    if addr_match:
        try:
            network = ipaddress.ip_network(
                f'{addr_match.group(1)}/{addr_match.group(2)}',
                strict=False,
            )
        except ValueError:
            return params
        params['subnet'] = str(network)
    return params


async def _run_text(*command: str) -> str:
    """Run a read-only command and return its stdout (empty on failure)."""
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return ''
    stdout, _ = await process.communicate()
    return stdout.decode(errors='replace')


def _ip_binary() -> str:
    """Resolve the `ip` binary, robust to a restricted systemd-service PATH.

    The core runs as a systemd user-service whose PATH may omit `/usr/sbin`,
    so a bare `ip` can fail to resolve in-process even though it exists — which
    would leave the macvlan form's discovered prefills blank.
    """
    candidates = ('/usr/sbin/ip', '/sbin/ip', '/bin/ip')
    return shutil.which('ip') or next(
        (path for path in candidates if Path(path).exists()),
        'ip',
    )


async def discover_lan_params() -> dict[str, str]:
    """Discover macvlan prefills from the host's routing table (best effort)."""
    ip_binary = _ip_binary()
    return parse_lan_params(
        await _run_text(ip_binary, 'route'),
        await _run_text(ip_binary, '-o', 'addr'),
    )


def _suggest_reserved_ip(subnet: str, gateway: str) -> str:
    """Suggest a high host address in the subnet for Home Assistant's macvlan IP.

    A high host (`broadcast - 5`) is likely outside the common low DHCP range;
    it's only a suggestion the user confirms. Returns '' when the subnet is
    invalid/too small or the candidate would collide with the gateway/edges.
    """
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return ''
    first = int(network.network_address)
    last = int(network.broadcast_address)
    candidate = last - 5
    if not first < candidate < last:
        return ''
    try:
        if gateway and candidate == int(ipaddress.ip_address(gateway)):
            candidate -= 1
    except ValueError:
        pass
    if candidate <= first:
        return ''
    # Rebuild in the subnet's address family (IPv4/IPv6).
    return str(type(network.network_address)(candidate))


MOSQUITTO_IMAGE = 'eclipse-mosquitto:2'
_MOSQUITTO_AUTH_SOURCE_PATH = '/mosquitto/config/passwd'
_MOSQUITTO_AUTH_RUNTIME_PATH = '/run/mosquitto/passwd'
# Two listeners with separate auth postures. 1883 stays anonymous but is only
# reachable on `ubo_net` (containers connect as `mosquitto:1883`, so the Home
# Assistant onboarding instructions need no credentials). 1884 requires the
# generated password below and is the listener published on the host's
# loopback (see `_write_home_assistant_compose`) — its only intended client is
# the pod's own MQTT bridge, which reads the secret programmatically. Without
# this split, any local process or secondary account on the pod could read all
# telemetry and, with remote control enabled, drive the command surface.
MOSQUITTO_CONF = (
    'per_listener_settings true\n'
    'listener 1883\n'
    'allow_anonymous true\n'
    'listener 1884\n'
    'allow_anonymous false\n'
    f'password_file {_MOSQUITTO_AUTH_RUNTIME_PATH}\n'
    'persistence true\n'
    'persistence_location /mosquitto/data/\n'
)

# Mosquitto 2.x `mosquitto_passwd` format: PBKDF2-HMAC-SHA512, tagged `$7$`,
# with the iteration count it uses by default. Verified against a live
# `eclipse-mosquitto:2` broker — do not change one without the other.
_MOSQUITTO_HASH_ITERATIONS = 1000
_MOSQUITTO_SALT_LENGTH = 64
_MOSQUITTO_KEY_LENGTH = 64


def _mosquitto_passwd_line(username: str, password: str) -> str:
    """Render one `password_file` entry the way `mosquitto_passwd` would."""
    salt = secrets.token_bytes(_MOSQUITTO_SALT_LENGTH)
    digest = hashlib.pbkdf2_hmac(
        'sha512',
        password.encode(),
        salt,
        _MOSQUITTO_HASH_ITERATIONS,
        dklen=_MOSQUITTO_KEY_LENGTH,
    )
    encoded_salt = base64.b64encode(salt).decode()
    encoded_digest = base64.b64encode(digest).decode()
    return (
        f'{username}:$7${_MOSQUITTO_HASH_ITERATIONS}'
        f'${encoded_salt}${encoded_digest}\n'
    )


def _bundled_broker_password() -> str:
    """Return the bundled broker's credential, generating it on first use.

    The password never needs to be typed by a human — the bridge reads it from
    the secrets file — so it is generated once and reused, keeping the broker's
    `password_file` and the bridge's view of it in sync across re-renders.
    """
    password = read_secret(BUNDLED_BROKER_PASSWORD_SECRET_ID)
    if not password:
        password = secrets.token_urlsafe(24)
        write_secret(key=BUNDLED_BROKER_PASSWORD_SECRET_ID, value=password)
    return password


def _write_mosquitto_config() -> None:
    """Write the Mosquitto config and password file to the bind-mount."""
    config_dir = HOME_ASSISTANT_DATA_PATH / 'mosquitto' / 'config'
    config_dir.mkdir(exist_ok=True, parents=True)
    (HOME_ASSISTANT_DATA_PATH / 'mosquitto' / 'data').mkdir(
        exist_ok=True,
        parents=True,
    )
    (config_dir / 'mosquitto.conf').write_text(MOSQUITTO_CONF)
    passwd_path = config_dir / 'passwd'
    passwd_path.write_text(
        _mosquitto_passwd_line(BUNDLED_BROKER_USERNAME, _bundled_broker_password()),
    )
    # Mosquitto warns on (and will eventually refuse) a world-readable
    # password file.
    passwd_path.chmod(0o600)


HA_MACVLAN_NETWORK = 'ha_macvlan'


def _ha_networks_block(macvlan: dict[str, str] | None) -> str:
    """HA service `networks:` block — multi-homed when macvlan is enabled."""
    if macvlan:
        return (
            '    networks:\n'
            f'      {UBO_NET}: {{}}\n'
            f'      {HA_MACVLAN_NETWORK}:\n'
            f'        ipv4_address: {macvlan["ip"]}\n'
        )
    return f'    networks:\n      - {UBO_NET}\n'


def _top_level_networks_block(macvlan: dict[str, str] | None) -> str:
    """Top-level `networks:` — adds the macvlan definition when enabled."""
    block = f'networks:\n  {UBO_NET}:\n    external: true\n'
    if macvlan:
        block += (
            f'  {HA_MACVLAN_NETWORK}:\n'
            '    driver: macvlan\n'
            '    driver_opts:\n'
            f'      parent: {macvlan["parent"]}\n'
            '    ipam:\n'
            '      config:\n'
            f'        - subnet: {macvlan["subnet"]}\n'
            f'          gateway: {macvlan["gateway"]}\n'
        )
    return block


def _write_home_assistant_compose(
    composition_path: Path,
    zigbee_device: str | None,
    macvlan: dict[str, str] | None = None,
) -> None:
    """Write HA's `docker-compose.yml` from current intent.

    Device-only privilege posture: no blanket `privileged: true`. The Zigbee
    coordinator is mapped in via a `devices:` entry (only when desired AND
    present); `/run/dbus` or extra capabilities are added only if a concrete
    integration needs them.

    The bundled Mosquitto broker lives in HA's project (HA owns its lifecycle)
    but is attached to the external `ubo_net` bus so peer add-ons can reach it
    as `mosquitto:1883`. Its *authenticated* listener (container port 1884,
    see `MOSQUITTO_CONF`) is additionally published on the host's loopback as
    127.0.0.1:1883 so the pod's MQTT bridge can publish readings to Home
    Assistant over MQTT discovery without exposing an anonymous broker to
    other local processes.

    That publish deliberately uses compose's *long* syntax:
    `apply_compose_port_binding` rewrites short-syntax entries only, so if HA
    ever opts into the expose-to-LAN toggle, 8123 can move to 0.0.0.0 while the
    broker stays pinned to loopback.

    When ``macvlan`` is given, HA is additionally attached to a macvlan network
    (its own LAN IP) so mDNS/SSDP discovery works; it stays multi-homed on
    ``ubo_net`` for the bus.
    """
    config_path = HOME_ASSISTANT_DATA_PATH / 'config'
    mosquitto_path = HOME_ASSISTANT_DATA_PATH / 'mosquitto'
    timezone = _detect_timezone()
    devices_block = (
        '    devices:\n'
        f'      - {zigbee_device}:{ZIGBEE_CONTAINER_DEVICE}\n'
        if zigbee_device
        else ''
    )
    compose_content = (
        'services:\n'
        '  homeassistant:\n'
        f'    image: {HOME_ASSISTANT_IMAGE}\n'
        '    container_name: homeassistant\n'
        '    restart: unless-stopped\n'
        '    environment:\n'
        f'      - TZ={timezone}\n'
        '    volumes:\n'
        f'      - {config_path}:/config\n'
        '      - /etc/localtime:/etc/localtime:ro\n'
        f'{devices_block}'
        '    ports:\n'
        '      - 8123:8123\n'
        f'{_ha_networks_block(macvlan)}'
        '  mosquitto:\n'
        f'    image: {MOSQUITTO_IMAGE}\n'
        '    container_name: mosquitto\n'
        '    restart: unless-stopped\n'
        '    command:\n'
        '      - /bin/sh\n'
        '      - -ec\n'
        '      - |\n'
        '        mkdir -p /run/mosquitto\n'
        '        chown root:root /run/mosquitto\n'
        '        chmod 755 /run/mosquitto\n'
        f'        cp {_MOSQUITTO_AUTH_SOURCE_PATH} '
        f'{_MOSQUITTO_AUTH_RUNTIME_PATH}\n'
        f'        chown mosquitto:mosquitto {_MOSQUITTO_AUTH_RUNTIME_PATH}\n'
        f'        chmod 600 {_MOSQUITTO_AUTH_RUNTIME_PATH}\n'
        '        exec /usr/sbin/mosquitto '
        '-c /mosquitto/config/mosquitto.conf\n'
        '    volumes:\n'
        f'      - {mosquitto_path / "config"}:/mosquitto/config\n'
        f'      - {mosquitto_path / "data"}:/mosquitto/data\n'
        '    ports:\n'
        '      - target: 1884\n'
        '        published: 1883\n'
        '        host_ip: 127.0.0.1\n'
        '        protocol: tcp\n'
        '    networks:\n'
        f'      - {UBO_NET}\n'
        f'{_top_level_networks_block(macvlan)}'
    )
    (composition_path / 'docker-compose.yml').write_text(compose_content)


def _write_home_assistant_metadata(composition_path: Path) -> None:
    metadata = {
        'label': HOME_ASSISTANT_LABEL,
        'icon': HOME_ASSISTANT_ICON,
        'instructions': (
            'Home Assistant is installed and running.\n\n'
            'Open port 8123 on this device in a browser to finish onboarding. '
            'Configuration is stored on the device and survives reinstalling '
            'the app.\n\n'
            'An MQTT broker is bundled. To connect it, add the MQTT '
            'integration in Home Assistant and point it at broker '
            '"mosquitto" port 1883 (no username or password).\n\n'
            'Once that is done, sensors plugged into this device appear in '
            'Home Assistant automatically — no further configuration.\n\n'
            'Advanced discovery (macvlan) gives Home Assistant its own LAN IP '
            'for mDNS/SSDP discovery. Note: while macvlan is enabled, this '
            'device (the Pod) cannot reach Home Assistant on its macvlan IP '
            'directly — use port 8123 on the device instead.'
        ),
        'compose_id': HOME_ASSISTANT_COMPOSITION_ID,
    }
    (composition_path / 'metadata.json').write_text(json.dumps(metadata))


async def prepare_home_assistant() -> bool:
    """Render HA's compose file + metadata and create persistent directories."""
    try:
        logger.info('Preparing Home Assistant composition')
        composition_path = COMPOSITIONS_PATH / HOME_ASSISTANT_COMPOSITION_ID
        composition_path.mkdir(exist_ok=True, parents=True)
        (HOME_ASSISTANT_DATA_PATH / 'config').mkdir(exist_ok=True, parents=True)
        _write_mosquitto_config()
        _write_home_assistant_compose(
            composition_path,
            _resolve_zigbee_device(),
            _resolve_macvlan(),
        )
        _write_home_assistant_metadata(composition_path)
    except Exception:
        logger.exception('Failed to prepare Home Assistant')
        return False
    else:
        return True


async def _choose_adapter(adapters: list[str]) -> str | None:
    """Prompt the user to pick one coordinator when several are plugged in."""
    try:
        _, result = await ubo_input(
            prompt='Select Zigbee adapter',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='adapter',
                            label='Adapter',
                            type=InputFieldType.SELECT,
                            options=adapters,
                            default_value=adapters[0],
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return None
    if not result:
        return None
    return (result.data.get('adapter') or '').strip() or None


def _recreate_home_assistant() -> None:
    """Re-render + recreate HA so a changed `devices:` mapping takes effect.

    `devices:` is read only at container *create*, so a plain restart wouldn't
    pick up the new mapping — `DockerImageRunAction` drives `run_composition`,
    which re-renders then `up -d` (recreate).
    """
    store.dispatch(DockerImageRunAction(image=HOME_ASSISTANT_COMPOSITION_ID))


async def _attach_zigbee() -> None:
    """Detect a coordinator, persist the intent, and recreate HA."""
    adapters = detect_serial_adapters()
    if not adapters:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title=HOME_ASSISTANT_LABEL,
                    content='No Zigbee adapter detected. Plug one in and retry.',
                    display_type=NotificationDisplayType.FLASH,
                    icon=HOME_ASSISTANT_ICON,
                ),
            ),
        )
        return
    adapter = adapters[0] if len(adapters) == 1 else await _choose_adapter(adapters)
    if adapter is None:
        return
    store.dispatch(
        DockerSetZigbeeIntentAction(enabled=True, adapter_by_id=adapter),
    )
    _recreate_home_assistant()


def _on_attach_zigbee() -> None:
    """Kick off the attach flow as a fire-and-forget task, returning None.

    Returning the ``create_task`` result (a Task) would push a stray empty
    submenu frame, so the task is launched and explicitly discarded.
    """
    create_task(_attach_zigbee())


def _detach_zigbee() -> None:
    """Clear the Zigbee intent and recreate HA without the mapping."""
    store.dispatch(DockerSetZigbeeIntentAction(enabled=False, adapter_by_id=''))
    _recreate_home_assistant()


async def _configure_macvlan() -> None:
    """Collect macvlan LAN params (discovery-prefilled) and recreate HA."""
    prefills = await discover_lan_params()
    suggested_ip = _suggest_reserved_ip(
        prefills.get('subnet', ''),
        prefills.get('gateway', ''),
    )
    try:
        _, result = await ubo_input(
            prompt='Advanced discovery (macvlan)',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='parent',
                            label='Parent interface',
                            type=InputFieldType.TEXT,
                            default_value=prefills.get('parent', ''),
                            required=True,
                        ),
                        InputFieldDescription(
                            name='subnet',
                            label='Subnet (CIDR)',
                            type=InputFieldType.TEXT,
                            default_value=prefills.get('subnet', ''),
                            required=True,
                        ),
                        InputFieldDescription(
                            name='gateway',
                            label='Gateway',
                            type=InputFieldType.TEXT,
                            default_value=prefills.get('gateway', ''),
                            required=True,
                        ),
                        InputFieldDescription(
                            name='ip',
                            label='Reserved IP for Home Assistant',
                            type=InputFieldType.TEXT,
                            default_value=suggested_ip,
                            description=(
                                'Suggested; confirm it is free and outside the '
                                'DHCP pool.'
                            ),
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if not result:
        return
    config = {
        'parent': (result.data.get('parent') or '').strip(),
        'subnet': (result.data.get('subnet') or '').strip(),
        'gateway': (result.data.get('gateway') or '').strip(),
        'ip': (result.data.get('ip') or '').strip(),
    }
    if not all(config.values()) or not _is_valid_macvlan(config):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title=HOME_ASSISTANT_LABEL,
                    content=(
                        'Invalid macvlan settings. Enter a valid interface '
                        'name, subnet (CIDR), gateway and reserved IP.'
                    ),
                    display_type=NotificationDisplayType.FLASH,
                    icon=HOME_ASSISTANT_ICON,
                ),
            ),
        )
        return
    store.dispatch(
        DockerSetMacvlanConfigAction(
            enabled=True,
            parent=config['parent'],
            subnet=config['subnet'],
            gateway=config['gateway'],
            ip=config['ip'],
        ),
    )
    _recreate_home_assistant()


def _on_configure_macvlan() -> None:
    """Launch the macvlan config flow as a fire-and-forget task (returns None)."""
    create_task(_configure_macvlan())


def _disable_macvlan() -> None:
    """Disable macvlan (back to bridge-only) and recreate HA."""
    store.dispatch(DockerSetMacvlanConfigAction(enabled=False))
    _recreate_home_assistant()


@store.with_state(lambda state: state.docker.service.macvlan_enabled)
def _macvlan_enabled(macvlan_enabled: bool) -> bool:  # noqa: FBT001
    """Read whether macvlan advanced discovery is currently enabled."""
    return macvlan_enabled


def _zigbee_submenu_view(
    *,
    enabled: bool,
    adapter_by_id: str,
    adapters: list[str],
) -> tuple[str, str, str, bool]:
    """Compute the Zigbee submenu's (heading, sub_heading, label, is_detach).

    Pure decision logic so it's unit-testable without the store. Driven by the
    desired intent (`enabled`); the adapter list only colours the status line.
    """
    if enabled:
        present = adapter_by_id in adapters
        sub_heading = adapter_by_id if present else 'adapter not detected'
        return 'Attached', sub_heading, 'Detach adapter', True
    sub_heading = 'Adapter detected' if adapters else 'No adapter detected'
    return 'Not attached', sub_heading, 'Attach adapter', False


def _menu_actions(
    menu_id: str,
    items: list[MenuItemData],
    action_ids: dict[str, list[str]],
) -> None:
    """Collapse Zigbee + macvlan into a 'Zigbee' submenu and an 'Advanced' one.

    Each submenu shows only the single action relevant to the current state
    (Attach/Detach, Enable/Disable), instead of cluttering the main menu with
    both directions of each toggle. Runs inside the docker menu autorun, so it
    re-renders reactively when the Zigbee/macvlan intent changes.
    """
    submenu_prefix = f'docker:image:{HOME_ASSISTANT_COMPOSITION_ID}'

    # --- Zigbee submenu ---
    zigbee_nav_id = 'docker:home_assistant:zigbee'
    zigbee_action_id = 'docker:home_assistant:zigbee-action'
    action_ids[menu_id].append(zigbee_nav_id)
    register_action(
        zigbee_nav_id,
        lambda: store.dispatch(StackPushMenuAction(menu_key='zigbee')),
    )
    items.append(
        MenuItemData(
            key='zigbee',
            label='Zigbee',
            icon='󰂜',
            action_id=zigbee_nav_id,
        ),
    )

    enabled, adapter_by_id = _zigbee_intent()
    heading, sub_heading, item_label, is_detach = _zigbee_submenu_view(
        enabled=enabled,
        adapter_by_id=adapter_by_id,
        adapters=detect_serial_adapters(),
    )
    action_ids[menu_id].append(zigbee_action_id)
    register_action(
        zigbee_action_id,
        _detach_zigbee if is_detach else _on_attach_zigbee,
    )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=f'{submenu_prefix}:zigbee',
            title='Zigbee',
            heading=heading,
            sub_heading=sub_heading,
            items=(
                MenuItemData(
                    key='zigbee-action',
                    label=item_label,
                    icon='󰂝' if is_detach else '󰂜',
                    action_id=zigbee_action_id,
                ),
            ),
        ),
    )

    # --- Advanced submenu (macvlan) ---
    advanced_nav_id = 'docker:home_assistant:advanced'
    macvlan_action_id = 'docker:home_assistant:macvlan-action'
    action_ids[menu_id].append(advanced_nav_id)
    register_action(
        advanced_nav_id,
        lambda: store.dispatch(StackPushMenuAction(menu_key='advanced')),
    )
    items.append(
        MenuItemData(
            key='advanced',
            label='Advanced',
            icon='󰒓',
            action_id=advanced_nav_id,
        ),
    )

    macvlan_on = _macvlan_enabled()
    action_ids[menu_id].append(macvlan_action_id)
    register_action(
        macvlan_action_id,
        _disable_macvlan if macvlan_on else _on_configure_macvlan,
    )
    macvlan_label = (
        'Disable advanced discovery'
        if macvlan_on
        else 'Advanced discovery (macvlan)'
    )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=f'{submenu_prefix}:advanced',
            title='Advanced',
            heading='LAN discovery',
            sub_heading='macvlan gives Home Assistant its own LAN IP',
            items=(
                MenuItemData(
                    key='macvlan',
                    label=macvlan_label,
                    icon='󰛳',
                    action_id=macvlan_action_id,
                ),
            ),
        ),
    )


ENTRY = ContainerEntry(
    id=HOME_ASSISTANT_COMPOSITION_ID,
    label=HOME_ASSISTANT_LABEL,
    icon=HOME_ASSISTANT_ICON,
    path=HOME_ASSISTANT_IMAGE,
    registry='docker.io',
    prepare=prepare_home_assistant,
    is_composition=True,
    category='Home Automation',
    menu_actions=_menu_actions,
)
