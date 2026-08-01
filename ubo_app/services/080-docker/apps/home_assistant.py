"""Home Assistant Docker composition.

Home Assistant ships as a Compose-managed stack (rather than a single
container) so it can anchor an add-on ecosystem on the shared `ubo_net`
bridge: a bundled MQTT broker, optional host-network discovery, and Zigbee USB
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
import json
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from apps._port_binding import LOOPBACK_IP
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
    DockerSetHostNetworkAction,
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
    return (
        enabled
        and bool(adapter_by_id)
        and (adapter_by_id not in detect_serial_adapters())
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


@store.with_state(lambda state: state.docker.service.host_network_enabled)
def _resolve_host_network(host_network_enabled: bool) -> bool:  # noqa: FBT001
    """Read whether HA should be rendered onto the host's network stack."""
    return host_network_enabled


@store.with_state(lambda state: getattr(state, 'mqtt', None))
def _resolve_broker_expose_to_lan(mqtt_state: object) -> bool:
    """Read whether the bundled broker's port should bind every interface.

    Guarded with `getattr` because the MQTT service can be disabled, and
    `state.mqtt` *raises* rather than returning None when its slice is absent —
    the same guard `050-mqtt/client.py` uses to read the docker slice. A missing
    slice reads as "loopback only", the safe direction.
    """
    return getattr(mqtt_state, 'bundled_expose_to_lan', False) is True


MOSQUITTO_IMAGE = 'eclipse-mosquitto:2'
_MOSQUITTO_AUTH_SOURCE_PATH = '/mosquitto/config/passwd'
_MOSQUITTO_AUTH_RUNTIME_PATH = '/run/mosquitto/passwd'
# One listener, authenticated for everyone. There is deliberately no anonymous
# path: an earlier split kept 1883 anonymous "because it is only reachable on
# `ubo_net`", but that is not a boundary the pod controls — on Linux the host
# routes to bridge addresses — and it forced the broker's address to differ
# between Home Assistant's two network modes. With auth as the only boundary,
# `mosquitto:1883` is the answer everywhere, and publishing the port to the LAN
# becomes a safe, ordinary toggle.
MOSQUITTO_CONF = (
    'listener 1883\n'
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


def _ha_network_block(*, host_network: bool) -> str:
    """HA's networking stanza — host stack, or the `ubo_net` bridge.

    Compose rejects `network_mode` alongside `networks:`, so host mode takes HA
    off the bus. The `extra_hosts` shim keeps the broker answering to the *same*
    name either way: on the bus it is the container, on the host stack it is the
    loopback publish. Both reach the same authenticated listener, so an MQTT
    integration configured once keeps working across the toggle.
    """
    if host_network:
        return (
            '    network_mode: host\n'
            '    extra_hosts:\n'
            f'      - "mosquitto:{LOOPBACK_IP}"\n'
        )
    return f'    networks:\n      - {UBO_NET}\n'


def _ha_ports_block(*, host_network: bool) -> str:
    """HA's `ports:` block — omitted in host mode, where it isn't allowed."""
    if host_network:
        return ''
    return '    ports:\n      - 8123:8123\n'


def _mosquitto_ports_block(*, expose_to_lan: bool) -> str:
    """Publish the broker on loopback, or on every interface when asked.

    Compose's *long* syntax deliberately: `apply_compose_port_binding` rewrites
    short-syntax entries only, so if Home Assistant ever opts into the per-app
    expose-to-LAN toggle, 8123 can move to 0.0.0.0 without dragging the broker
    along. The broker's own exposure is its own decision, made here.
    """
    block = '    ports:\n      - target: 1883\n        published: 1883\n'
    if not expose_to_lan:
        block += f'        host_ip: {LOOPBACK_IP}\n'
    return block + '        protocol: tcp\n'


def _write_home_assistant_compose(
    composition_path: Path,
    zigbee_device: str | None,
    *,
    host_network: bool = False,
    broker_expose_to_lan: bool = False,
) -> None:
    """Write HA's `docker-compose.yml` from current intent.

    Device-only privilege posture: no blanket `privileged: true`. The Zigbee
    coordinator is mapped in via a `devices:` entry (only when desired AND
    present); `/run/dbus` or extra capabilities are added only if a concrete
    integration needs them.

    The bundled Mosquitto broker lives in HA's project (HA owns its lifecycle)
    but is attached to the external `ubo_net` bus so peer add-ons can reach it
    as `mosquitto:1883`. Every connection authenticates (see `MOSQUITTO_CONF`),
    so the same listener serves the bus, the pod's own MQTT bridge on loopback,
    and — when ``broker_expose_to_lan`` is set — any client on the network.

    When ``host_network`` is set, HA runs on the host's network stack so
    mDNS/SSDP discovery works (the only option that works over Wi-Fi — a
    macvlan sub-interface has its own MAC, which an access point silently
    drops). It then binds 8123 on the host directly and leaves ``ubo_net``,
    reaching the broker through the loopback publish instead — under the same
    name, via `extra_hosts`.
    """
    config_path = HOME_ASSISTANT_DATA_PATH / 'config'
    mosquitto_path = HOME_ASSISTANT_DATA_PATH / 'mosquitto'
    timezone = _detect_timezone()
    devices_block = (
        f'    devices:\n      - {zigbee_device}:{ZIGBEE_CONTAINER_DEVICE}\n'
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
        '    extra_hosts:\n'
        '      - host.docker.internal:host-gateway\n'
        '    volumes:\n'
        f'      - {config_path}:/config\n'
        '      - /etc/localtime:/etc/localtime:ro\n'
        f'{devices_block}'
        f'{_ha_ports_block(host_network=host_network)}'
        f'{_ha_network_block(host_network=host_network)}'
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
        f'{_mosquitto_ports_block(expose_to_lan=broker_expose_to_lan)}'
        '    networks:\n'
        f'      - {UBO_NET}\n'
        f'networks:\n  {UBO_NET}:\n    external: true\n'
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
            '"mosquitto" port 1883. It asks for a username and password: find '
            'them on this device under Settings > MQTT > Bundled broker. That '
            'address is correct in either network mode.\n\n'
            'Once that is done, sensors plugged into this device appear in '
            'Home Assistant automatically — no further configuration.\n\n'
            'LAN discovery (host network) puts Home Assistant on this '
            "device's network stack so mDNS/SSDP discovery finds your "
            'devices — the only mode that works over Wi-Fi. Home Assistant '
            'stays on port 8123 either way.\n\n'
            "To use this Home Assistant installation with the Pod's Wyoming "
            'voice services, open Settings → Assistant → Satellites → Wyoming '
            'on the Pod, enable the listeners and select the Docker-only '
            'connection policy. Configure the Wyoming integrations with '
            'host.docker.internal on ports 10700 (satellite) and 10600 (ASR, '
            'TTS, and conversation).'
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
            host_network=_resolve_host_network(),
            broker_expose_to_lan=_resolve_broker_expose_to_lan(),
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


def _enable_host_network() -> None:
    """Move HA onto the host network stack and recreate it.

    Host mode costs HA its `ubo_net` membership, but not its broker: the
    `extra_hosts` shim keeps `mosquitto:1883` resolving, so a configured MQTT
    integration survives the toggle untouched.
    """
    store.dispatch(DockerSetHostNetworkAction(enabled=True))
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title=HOME_ASSISTANT_LABEL,
                content=(
                    "Home Assistant now shares this device's network so it "
                    'can discover LAN devices. It stays on port 8123.'
                ),
                display_type=NotificationDisplayType.FLASH,
                icon=HOME_ASSISTANT_ICON,
            ),
        ),
    )
    _recreate_home_assistant()


def _disable_host_network() -> None:
    """Put HA back on the `ubo_net` bridge and recreate it."""
    store.dispatch(DockerSetHostNetworkAction(enabled=False))
    _recreate_home_assistant()


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
    """Collapse Zigbee + LAN discovery into a 'Zigbee' and an 'Advanced' submenu.

    Each submenu shows only the single action relevant to the current state
    (Attach/Detach, Enable/Disable), instead of cluttering the main menu with
    both directions of each toggle. Runs inside the docker menu autorun, so it
    re-renders reactively when the Zigbee/host-network intent changes.
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

    # --- Advanced submenu (LAN discovery) ---
    advanced_nav_id = 'docker:home_assistant:advanced'
    host_network_action_id = 'docker:home_assistant:host-network-action'
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

    host_network_on = _resolve_host_network()
    action_ids[menu_id].append(host_network_action_id)
    register_action(
        host_network_action_id,
        _disable_host_network if host_network_on else _enable_host_network,
    )
    host_network_label = (
        'Disable LAN discovery' if host_network_on else 'LAN discovery (host network)'
    )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=f'{submenu_prefix}:advanced',
            title='Advanced',
            heading='LAN discovery',
            sub_heading="Shares this device's network for mDNS/SSDP",
            items=(
                MenuItemData(
                    key='host-network',
                    label=host_network_label,
                    icon='󰛳',
                    action_id=host_network_action_id,
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
