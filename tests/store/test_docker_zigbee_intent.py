"""Tests for the Docker Zigbee-passthrough intent reducer behavior."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


def _reducer_module() -> ModuleType:
    """Import the Docker reducer the way the service loader does."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)
    try:
        return import_module('reducer')
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


@pytest.fixture(autouse=True)
def _isolated_persistent_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep DockerServiceState's persistent-store reads off the real file."""
    store_path = tmp_path / 'state.json'
    monkeypatch.setattr('ubo_app.constants.PERSISTENT_STORE_PATH', store_path)
    monkeypatch.setattr(
        'ubo_app.utils.persistent_store.PERSISTENT_STORE_PATH',
        store_path,
    )


def test_set_zigbee_intent_enables_with_adapter() -> None:
    """Enabling passthrough persists the chosen adapter's by-id path."""
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    state = service_reducer(None, reducer_module.InitAction())

    result = service_reducer(
        state,
        reducer_module.DockerSetZigbeeIntentAction(
            enabled=True,
            adapter_by_id='/dev/serial/by-id/usb-A-if00-port0',
        ),
    )

    assert result.zigbee_enabled is True
    assert result.zigbee_adapter_by_id == '/dev/serial/by-id/usb-A-if00-port0'


def test_detach_clears_zigbee_intent() -> None:
    """Detaching clears both the flag and the adapter path."""
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    set_intent = reducer_module.DockerSetZigbeeIntentAction

    state = service_reducer(None, reducer_module.InitAction())
    state = service_reducer(
        state,
        set_intent(enabled=True, adapter_by_id='/dev/serial/by-id/x'),
    )
    result = service_reducer(state, set_intent(enabled=False, adapter_by_id=''))

    assert result.zigbee_enabled is False
    assert result.zigbee_adapter_by_id == ''


def test_set_macvlan_config_persists_params() -> None:
    """Enabling macvlan stores all four LAN parameters."""
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    state = service_reducer(None, reducer_module.InitAction())

    result = service_reducer(
        state,
        reducer_module.DockerSetMacvlanConfigAction(
            enabled=True,
            parent='eth0',
            subnet='192.168.1.0/24',
            gateway='192.168.1.1',
            ip='192.168.1.50',
        ),
    )

    assert result.macvlan_enabled is True
    assert result.macvlan_parent == 'eth0'
    assert result.macvlan_subnet == '192.168.1.0/24'
    assert result.macvlan_gateway == '192.168.1.1'
    assert result.macvlan_ip == '192.168.1.50'


def test_disable_macvlan_clears_params() -> None:
    """Disabling macvlan clears the stored parameters."""
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    set_macvlan = reducer_module.DockerSetMacvlanConfigAction

    state = service_reducer(None, reducer_module.InitAction())
    state = service_reducer(
        state,
        set_macvlan(
            enabled=True,
            parent='eth0',
            subnet='192.168.1.0/24',
            gateway='192.168.1.1',
            ip='192.168.1.50',
        ),
    )
    result = service_reducer(state, set_macvlan(enabled=False))

    assert result.macvlan_enabled is False
    assert result.macvlan_parent == ''
    assert result.macvlan_ip == ''
