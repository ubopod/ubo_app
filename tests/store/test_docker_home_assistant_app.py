"""Tests for the Home Assistant Docker composition app."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

import pytest

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


class HomeAssistantModule(Protocol):
    """Protocol for the Home Assistant module members used by these tests."""

    COMPOSITIONS_PATH: Path
    HOME_ASSISTANT_DATA_PATH: Path
    HOME_ASSISTANT_COMPOSITION_ID: str
    UBO_NET: str
    SERIAL_BY_ID_PATH: Path
    ZIGBEE_CONTAINER_DEVICE: str
    BUNDLED_BROKER_USERNAME: str
    BUNDLED_BROKER_PASSWORD_SECRET_ID: str

    def detect_serial_adapters(self) -> list[str]:
        """Enumerate serial-by-id adapters."""
        ...

    def _resolve_zigbee_device(self) -> str | None: ...

    def _zigbee_intent(self) -> tuple[bool, str]: ...

    def _notify_zigbee_degraded(self) -> None: ...

    def _write_home_assistant_compose(
        self,
        composition_path: Path,
        zigbee_device: str | None,
        *,
        host_network: bool = False,
        broker_expose_to_lan: bool = False,
    ) -> None: ...

    def _zigbee_submenu_view(
        self,
        *,
        enabled: bool,
        adapter_by_id: str,
        adapters: list[str],
    ) -> tuple[str, str, str, bool]: ...

    async def prepare_home_assistant(self) -> bool:
        """Render Home Assistant composition files."""
        ...


def _disable_zigbee(
    monkeypatch: pytest.MonkeyPatch,
    ha: HomeAssistantModule,
) -> None:
    """Bypass the store-backed Zigbee + host-network resolution for renders."""
    monkeypatch.setattr(ha, '_resolve_zigbee_device', lambda: None)
    monkeypatch.setattr(ha, '_resolve_host_network', lambda: False)
    monkeypatch.setattr(ha, '_resolve_broker_expose_to_lan', lambda: False)


def _import_home_assistant() -> HomeAssistantModule:
    """Import the Home Assistant module as the Docker service would."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)

    try:
        return cast('HomeAssistantModule', import_module('apps.home_assistant'))
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


@pytest.fixture(autouse=True)
def bundled_broker_secrets(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Keep the generated broker credential out of the real secrets file."""
    ha = _import_home_assistant()
    store: dict[str, str] = {}

    def _write_secret(*, key: str, value: str) -> None:
        store[key] = value

    monkeypatch.setattr(ha, 'read_secret', store.get)
    monkeypatch.setattr(ha, 'write_secret', _write_secret)
    return store


async def test_prepare_renders_compose_on_ubo_net(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The prepare phase authors a compose attached to the external ubo_net."""
    ha = _import_home_assistant()
    compositions = tmp_path / 'compositions'
    data = tmp_path / 'data'
    monkeypatch.setattr(ha, 'COMPOSITIONS_PATH', compositions)
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', data)
    _disable_zigbee(monkeypatch, ha)

    assert await ha.prepare_home_assistant()

    compose = (
        compositions / ha.HOME_ASSISTANT_COMPOSITION_ID / 'docker-compose.yml'
    ).read_text()
    # Attached to the shared external bus, not a private network.
    assert f'      - {ha.UBO_NET}\n' in compose
    assert f'  {ha.UBO_NET}:\n    external: true\n' in compose
    # Persistent config bind-mount lives OUTSIDE the composition directory so
    # `down -v` / composition-dir removal can't destroy it.
    assert f'- {data / "config"}:/config' in compose
    assert str(compositions) not in f'{data / "config"}'
    # Shape essentials.
    assert 'image: homeassistant/home-assistant:stable' in compose
    assert 'restart: unless-stopped' in compose
    assert '- 8123:8123' in compose
    assert 'TZ=' in compose
    assert 'extra_hosts:' in compose
    assert '- host.docker.internal:host-gateway' in compose
    # No blanket privilege escalation in the device-only posture.
    assert 'privileged' not in compose
    # The bundled MQTT broker rides the same external bus (containers reach it
    # as mosquitto:1883) and is published on the host's loopback so the pod's
    # own bridge can publish readings to it. Loopback by default — never
    # 0.0.0.0 unless the user asks for it.
    assert 'mosquitto:' in compose
    assert 'image: eclipse-mosquitto' in compose
    assert 'host_ip: 127.0.0.1\n' in compose
    assert '- target: 1883\n' in compose
    assert 'published: 1883\n' in compose
    # The bare short-syntax form would bind every interface — it must not appear.
    assert '- 1883:1883' not in compose
    mosquitto_conf = (
        data / 'mosquitto' / 'config' / 'mosquitto.conf'
    ).read_text()
    # One listener, authenticated for everyone: there is no anonymous path, so
    # the same address and credentials work from the bus, from loopback, and
    # from the LAN.
    assert 'per_listener_settings' not in mosquitto_conf
    assert 'allow_anonymous true' not in mosquitto_conf
    assert '1884' not in mosquitto_conf
    assert (
        'listener 1883\nallow_anonymous false\n'
        'password_file /run/mosquitto/passwd\n' in mosquitto_conf
    )
    assert 'mkdir -p /run/mosquitto\n' in compose
    assert 'cp /mosquitto/config/passwd /run/mosquitto/passwd\n' in compose
    assert 'chown mosquitto:mosquitto /run/mosquitto/passwd\n' in compose
    assert 'chmod 600 /run/mosquitto/passwd\n' in compose
    assert (
        'exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf\n' in compose
    )


async def test_mosquitto_password_file_is_generated_and_stable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bundled_broker_secrets: dict[str, str],
) -> None:
    """The broker credential is generated once, hashed, and kept private.

    The password itself lives in the secrets file (the bridge reads it from
    there); the broker only ever sees the `mosquitto_passwd`-format hash, and
    a re-render reuses the stored secret so the two stay in sync.
    """
    ha = _import_home_assistant()
    compositions = tmp_path / 'compositions'
    data = tmp_path / 'data'
    monkeypatch.setattr(ha, 'COMPOSITIONS_PATH', compositions)
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', data)
    _disable_zigbee(monkeypatch, ha)

    assert await ha.prepare_home_assistant()

    passwd_path = data / 'mosquitto' / 'config' / 'passwd'
    line = passwd_path.read_text()
    password = bundled_broker_secrets[ha.BUNDLED_BROKER_PASSWORD_SECRET_ID]
    # `user:$7$<iterations>$<salt-b64>$<digest-b64>` — and never the cleartext.
    assert line.startswith(f'{ha.BUNDLED_BROKER_USERNAME}:$7$')
    assert password not in line
    assert passwd_path.stat().st_mode & 0o077 == 0
    _, _, iterations, salt, digest = line.strip().split('$')
    import base64
    import hashlib

    assert base64.b64decode(digest) == hashlib.pbkdf2_hmac(
        'sha512',
        password.encode(),
        base64.b64decode(salt),
        int(iterations),
        dklen=len(base64.b64decode(digest)),
    )

    # A second render must not rotate the credential out from under the
    # bridge's copy in the secrets file.
    assert await ha.prepare_home_assistant()
    assert bundled_broker_secrets[ha.BUNDLED_BROKER_PASSWORD_SECRET_ID] == password


async def test_broker_stays_on_loopback_when_exposed_to_lan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exposing Home Assistant to the LAN must not expose the MQTT broker.

    The host-published listener is authenticated, but it is still not meant
    for the LAN. `apply_compose_port_binding` rewrites short-syntax ports
    only, which is exactly why the broker's publish uses the long form: HA's
    8123 moves, the broker does not.
    """
    import sys

    ha = _import_home_assistant()
    compositions = tmp_path / 'compositions'
    data = tmp_path / 'data'
    monkeypatch.setattr(ha, 'COMPOSITIONS_PATH', compositions)
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', data)
    _disable_zigbee(monkeypatch, ha)

    assert await ha.prepare_home_assistant()
    compose = (
        compositions / ha.HOME_ASSISTANT_COMPOSITION_ID / 'docker-compose.yml'
    ).read_text()

    sys.path.insert(0, str(DOCKER_SERVICE_PATH))
    try:
        from apps._port_binding import (  # type: ignore[import-not-found]
            apply_compose_port_binding,
        )
    finally:
        sys.path.remove(str(DOCKER_SERVICE_PATH))

    exposed = apply_compose_port_binding(compose, expose_to_lan=True)

    # HA's own port is free to move to every interface ...
    assert '- 8123:8123' in exposed
    # ... but the broker keeps its explicit loopback binding.
    assert 'host_ip: 127.0.0.1\n' in exposed
    assert '- 1883:1883' not in exposed
    assert '- 0.0.0.0:1883:1883' not in exposed


async def test_prepare_creates_persistent_config_dir_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Prepare creates the persistent config dir and writes instructions."""
    ha = _import_home_assistant()
    compositions = tmp_path / 'compositions'
    data = tmp_path / 'data'
    monkeypatch.setattr(ha, 'COMPOSITIONS_PATH', compositions)
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', data)
    _disable_zigbee(monkeypatch, ha)

    assert await ha.prepare_home_assistant()

    assert (data / 'config').is_dir()
    metadata = (
        compositions / ha.HOME_ASSISTANT_COMPOSITION_ID / 'metadata.json'
    ).read_text()
    assert 'instructions' in metadata
    assert '8123' in metadata


async def test_prepare_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Re-rendering produces a stable compose file (derived artifact)."""
    ha = _import_home_assistant()
    compositions = tmp_path / 'compositions'
    monkeypatch.setattr(ha, 'COMPOSITIONS_PATH', compositions)
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', tmp_path / 'data')
    _disable_zigbee(monkeypatch, ha)

    assert await ha.prepare_home_assistant()
    compose_path = (
        compositions / ha.HOME_ASSISTANT_COMPOSITION_ID / 'docker-compose.yml'
    )
    first = compose_path.read_text()
    assert await ha.prepare_home_assistant()
    assert compose_path.read_text() == first


def test_detect_serial_adapters_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Enumeration returns 0/1/many adapters, sorted."""
    ha = _import_home_assistant()
    by_id = tmp_path / 'by-id'
    by_id.mkdir()
    monkeypatch.setattr(ha, 'SERIAL_BY_ID_PATH', by_id)

    assert ha.detect_serial_adapters() == []

    (by_id / 'usb-A-if00-port0').write_text('')
    (by_id / 'usb-B-if00-port0').write_text('')
    adapters = ha.detect_serial_adapters()
    assert len(adapters) == 2
    assert adapters == sorted(adapters)


def test_detect_serial_adapters_missing_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A missing /dev/serial/by-id (no adapters ever) yields an empty list."""
    ha = _import_home_assistant()
    monkeypatch.setattr(ha, 'SERIAL_BY_ID_PATH', tmp_path / 'nonexistent')
    assert ha.detect_serial_adapters() == []


def test_resolve_zigbee_device_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desired-off → no device mapping, no notification."""
    ha = _import_home_assistant()
    monkeypatch.setattr(ha, '_zigbee_intent', lambda: (False, ''))
    monkeypatch.setattr(ha, 'detect_serial_adapters', lambda: ['/dev/serial/by-id/x'])
    notified = []
    monkeypatch.setattr(ha, '_notify_zigbee_degraded', lambda: notified.append(True))

    assert ha._resolve_zigbee_device() is None  # noqa: SLF001
    assert not notified


def test_resolve_zigbee_device_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desired-on + adapter present → that adapter's by-id path."""
    ha = _import_home_assistant()
    adapter = '/dev/serial/by-id/usb-A-if00-port0'
    monkeypatch.setattr(ha, '_zigbee_intent', lambda: (True, adapter))
    monkeypatch.setattr(ha, 'detect_serial_adapters', lambda: [adapter])
    monkeypatch.setattr(ha, '_notify_zigbee_degraded', lambda: None)

    assert ha._resolve_zigbee_device() == adapter  # noqa: SLF001


def test_resolve_zigbee_device_absent_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desired-on + adapter absent → no mapping + degraded notification."""
    ha = _import_home_assistant()
    monkeypatch.setattr(
        ha,
        '_zigbee_intent',
        lambda: (True, '/dev/serial/by-id/gone'),
    )
    monkeypatch.setattr(ha, 'detect_serial_adapters', list)
    notified = []
    monkeypatch.setattr(ha, '_notify_zigbee_degraded', lambda: notified.append(True))

    assert ha._resolve_zigbee_device() is None  # noqa: SLF001
    assert notified == [True]


def test_compose_includes_devices_when_adapter_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An adapter path renders a `devices:` mapping to the fixed container path."""
    ha = _import_home_assistant()
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', tmp_path / 'data')
    composition_path = tmp_path / 'composition'
    composition_path.mkdir()
    adapter = '/dev/serial/by-id/usb-A-if00-port0'

    ha._write_home_assistant_compose(composition_path, adapter)  # noqa: SLF001
    compose = (composition_path / 'docker-compose.yml').read_text()
    assert 'devices:' in compose
    assert f'- {adapter}:{ha.ZIGBEE_CONTAINER_DEVICE}' in compose

    # No adapter → no devices block (graceful absence).
    ha._write_home_assistant_compose(composition_path, None)  # noqa: SLF001
    compose = (composition_path / 'docker-compose.yml').read_text()
    assert 'devices:' not in compose


def test_compose_uses_host_network_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Host-network mode takes HA off the bridge and onto the host stack."""
    ha = _import_home_assistant()
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', tmp_path / 'data')
    composition_path = tmp_path / 'composition'
    composition_path.mkdir()

    ha._write_home_assistant_compose(  # noqa: SLF001
        composition_path,
        None,
        host_network=True,
    )
    compose = (composition_path / 'docker-compose.yml').read_text()
    ha_block = compose.split('  mosquitto:')[0]
    assert 'network_mode: host' in ha_block
    # Compose rejects `network_mode` alongside `networks:`, and `ports:` is not
    # permitted either — HA binds 8123 on the host directly.
    assert f'      - {ha.UBO_NET}\n' not in ha_block
    assert '- 8123:8123' not in compose
    # Off the bus, the broker answers under the same name via the loopback
    # publish — so an MQTT integration configured once survives the toggle.
    assert '- "mosquitto:127.0.0.1"' in ha_block
    # The broker itself is untouched: still on the bus, still loopback-bound.
    assert f'  {ha.UBO_NET}:\n    external: true\n' in compose
    assert 'host_ip: 127.0.0.1' in compose


def test_compose_stays_on_bridge_when_host_network_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bridge mode publishes 8123 and keeps HA on the shared bus."""
    ha = _import_home_assistant()
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', tmp_path / 'data')
    composition_path = tmp_path / 'composition'
    composition_path.mkdir()

    ha._write_home_assistant_compose(  # noqa: SLF001
        composition_path,
        None,
        host_network=False,
    )
    compose = (composition_path / 'docker-compose.yml').read_text()
    assert 'network_mode' not in compose
    # The host.docker.internal shim (for Wyoming) is unconditional; the
    # mosquitto-loopback shim is host-network-only.
    assert '- host.docker.internal:host-gateway' in compose
    assert '- "mosquitto:127.0.0.1"' not in compose
    assert '- 8123:8123' in compose
    assert f'      - {ha.UBO_NET}\n' in compose


def test_broker_binds_all_interfaces_when_exposed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exposing the broker drops its loopback pin; the port itself is unchanged.

    Safe to offer only because the listener authenticates — see
    `MOSQUITTO_CONF`, which has no anonymous path.
    """
    ha = _import_home_assistant()
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', tmp_path / 'data')
    composition_path = tmp_path / 'composition'
    composition_path.mkdir()

    ha._write_home_assistant_compose(  # noqa: SLF001
        composition_path,
        None,
        broker_expose_to_lan=True,
    )
    compose = (composition_path / 'docker-compose.yml').read_text()
    assert '- target: 1883\n        published: 1883\n' in compose
    assert 'host_ip' not in compose

    # Default stays pinned to loopback.
    ha._write_home_assistant_compose(  # noqa: SLF001
        composition_path,
        None,
        broker_expose_to_lan=False,
    )
    compose = (composition_path / 'docker-compose.yml').read_text()
    assert 'host_ip: 127.0.0.1\n' in compose


def test_zigbee_submenu_view_enabled_present() -> None:
    """Enabled + adapter present → Detach, adapter id in the status line."""
    ha = _import_home_assistant()
    adapter = '/dev/serial/by-id/usb-A-if00-port0'
    heading, sub_heading, label, is_detach = ha._zigbee_submenu_view(  # noqa: SLF001
        enabled=True,
        adapter_by_id=adapter,
        adapters=[adapter],
    )
    assert heading == 'Attached'
    assert sub_heading == adapter
    assert label == 'Detach adapter'
    assert is_detach is True


def test_zigbee_submenu_view_enabled_absent() -> None:
    """Enabled but the configured adapter is unplugged → status reflects that."""
    ha = _import_home_assistant()
    _, sub_heading, label, is_detach = ha._zigbee_submenu_view(  # noqa: SLF001
        enabled=True,
        adapter_by_id='/dev/serial/by-id/gone',
        adapters=[],
    )
    assert sub_heading == 'adapter not detected'
    assert label == 'Detach adapter'
    assert is_detach is True


def test_zigbee_submenu_view_disabled_states() -> None:
    """Disabled → Attach; status line reflects live presence."""
    ha = _import_home_assistant()
    heading, sub_heading, label, is_detach = ha._zigbee_submenu_view(  # noqa: SLF001
        enabled=False,
        adapter_by_id='',
        adapters=['/dev/serial/by-id/x'],
    )
    assert heading == 'Not attached'
    assert sub_heading == 'Adapter detected'
    assert label == 'Attach adapter'
    assert is_detach is False

    _, sub_heading, _, _ = ha._zigbee_submenu_view(  # noqa: SLF001
        enabled=False,
        adapter_by_id='',
        adapters=[],
    )
    assert sub_heading == 'No adapter detected'


async def test_prepare_honours_host_network_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The prepare phase renders whichever network mode the store holds."""
    ha = _import_home_assistant()
    compositions = tmp_path / 'compositions'
    monkeypatch.setattr(ha, 'COMPOSITIONS_PATH', compositions)
    monkeypatch.setattr(ha, 'HOME_ASSISTANT_DATA_PATH', tmp_path / 'data')
    monkeypatch.setattr(ha, '_resolve_zigbee_device', lambda: None)
    monkeypatch.setattr(ha, '_resolve_host_network', lambda: True)
    monkeypatch.setattr(ha, '_resolve_broker_expose_to_lan', lambda: False)

    assert await ha.prepare_home_assistant()

    compose = (
        compositions / ha.HOME_ASSISTANT_COMPOSITION_ID / 'docker-compose.yml'
    ).read_text()
    assert 'network_mode: host' in compose
