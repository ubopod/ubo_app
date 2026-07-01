"""Tests for the Node-RED Docker composition add-on (contract proof)."""

from __future__ import annotations

import os
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    import pytest

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


class NodeRedModule(Protocol):
    """Protocol for the Node-RED module members used by these tests."""

    COMPOSITIONS_PATH: Path
    NODE_RED_DATA_PATH: Path
    NODE_RED_COMPOSITION_ID: str
    UBO_NET: str
    ENTRY: object

    async def prepare_node_red(self) -> bool:
        """Render Node-RED composition files."""
        ...


def _import_node_red() -> NodeRedModule:
    """Import the Node-RED module as the Docker service would."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)
    try:
        return cast('NodeRedModule', import_module('apps.node_red'))
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


async def test_prepare_renders_compose_on_ubo_net(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Node-RED joins the external ubo_net bus and persists flows off-tree."""
    node_red = _import_node_red()
    compositions = tmp_path / 'compositions'
    data = tmp_path / 'data'
    monkeypatch.setattr(node_red, 'COMPOSITIONS_PATH', compositions)
    monkeypatch.setattr(node_red, 'NODE_RED_DATA_PATH', data)

    assert await node_red.prepare_node_red()

    compose = (
        compositions / node_red.NODE_RED_COMPOSITION_ID / 'docker-compose.yml'
    ).read_text()
    assert f'      - {node_red.UBO_NET}\n' in compose
    assert f'  {node_red.UBO_NET}:\n    external: true\n' in compose
    assert 'image: nodered/node-red' in compose
    # Flows persist OUTSIDE the composition directory.
    assert f'- {data / "data"}:/data' in compose
    assert str(compositions) not in f'{data / "data"}'
    assert (data / 'data').is_dir()
    # Pinned to the core process uid:gid so the uid-1000 image can write the
    # core-owned /data bind mount (otherwise EACCES crash-loop).
    assert f'user: "{os.getuid()}:{os.getgid()}"' in compose
    # Safe-by-default: the published port binds loopback in the source; LAN
    # exposure is opt-in via the port-binding helper (supports_lan_toggle).
    assert '"127.0.0.1:1880:1880"' in compose
    assert '- 1880:1880' not in compose


def test_entry_requires_mqtt() -> None:
    """The add-on declares its MQTT-bus dependency for the warn-on-install path."""
    node_red = _import_node_red()
    assert getattr(node_red.ENTRY, 'requires_mqtt', False) is True
    assert getattr(node_red.ENTRY, 'is_composition', False) is True


def test_entry_defaults_to_loopback() -> None:
    """Node-RED has no built-in auth, so its port defaults to loopback (toggle)."""
    node_red = _import_node_red()
    assert getattr(node_red.ENTRY, 'supports_lan_toggle', False) is True
