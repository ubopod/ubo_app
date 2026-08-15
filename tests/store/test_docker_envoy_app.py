"""Tests for the Envoy Docker app."""

from __future__ import annotations

import stat
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ubo_app.constants import CONFIG_PATH
from ubo_app.utils import IS_RPI

if TYPE_CHECKING:
    import pytest


DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'
# The browser's gRPC-web endpoint resolution. It used to be inlined in
# `client.tsx`; the fetch-streaming rewrite moved it here so the streaming
# transport could reach it without importing the React entry point.
WEB_APP_GRPC_ENDPOINT_PATH = (
    Path(__file__).parents[2]
    / 'ubo_app'
    / 'services'
    / '090-web-ui'
    / 'web-app'
    / 'src'
    / 'store'
    / 'grpc-endpoint.ts'
)


class EnvoyModule(Protocol):
    """Protocol for the Envoy module members used by these tests."""

    ENVOY_CONFIG_PATH: Path
    ENVOY_TEMPLATE_PATH: Path
    ENTRY: DockerEntry

    async def prepare_envoy(self) -> bool:
        """Prepare Envoy configuration."""
        ...


class DockerEntry(Protocol):
    """Protocol for Docker entry fields used by these tests."""

    label: str
    category: str | None


def _import_envoy() -> EnvoyModule:
    """Import the Envoy module as the Docker service would."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)

    try:
        return cast('EnvoyModule', import_module('apps.envoy'))
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


async def test_prepare_envoy_renders_combined_webui_and_grpc_routes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Envoy fronts Web UI and gRPC-web on one listener."""
    envoy = _import_envoy()
    config_path = tmp_path / 'envoy.yaml'
    monkeypatch.setattr(envoy, 'ENVOY_CONFIG_PATH', config_path)

    assert await envoy.prepare_envoy()

    config = config_path.read_text()
    assert 'port_value: 50052' in config
    assert 'name: web_ui_cluster' in config
    # On the Pi the envoy container runs with ``network_mode='host'`` so it
    # reaches the gRPC server over loopback; off-device it lives on a
    # bridge network and reaches the host via the docker-magic DNS name.
    # ``apps/envoy.py:prepare_envoy`` branches on ``IS_RPI`` for this — the
    # assertion has to follow.
    expected_server_host = '127.0.0.1' if IS_RPI else 'host.docker.internal'
    assert f'address: {expected_server_host}' in config
    assert 'port_value: 4321' in config
    assert 'name: grpc_service_cluster' in config
    assert "prefix: '/grpc/'" in config
    assert "prefix_rewrite: '/'" in config
    assert config.index("prefix: '/grpc/'") < config.index("prefix: '/'")

    # The container drops to its non-root ``envoy`` user before reading the
    # bind-mounted config, so the rendered file must stay world-readable.
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o644


def test_envoy_config_renders_outside_versioned_install_tree() -> None:
    """The rendered config lives under CONFIG_PATH, not the versioned tree.

    The installer runs ``chmod -R 700 /opt/ubo/<version>`` on every update, which
    would make a config rendered inside that tree unreadable to the container's
    non-root envoy user (and its path changes on every version bump). Keeping it
    under ``CONFIG_PATH`` (stable, untouched by that chmod) is what makes the
    Envoy container survive updates.
    """
    envoy = _import_envoy()

    assert CONFIG_PATH in envoy.ENVOY_CONFIG_PATH.parents
    assert DOCKER_SERVICE_PATH not in envoy.ENVOY_CONFIG_PATH.parents


def test_web_ui_grpc_client_uses_same_origin_grpc_path() -> None:
    """The browser client routes gRPC-web through Envoy."""
    endpoint_source = WEB_APP_GRPC_ENDPOINT_PATH.read_text()

    assert 'window.location.port === window.WEB_UI_CONFIG.webUiListenPort' in (
        endpoint_source
    )
    assert 'window.WEB_UI_CONFIG.grpcEnvoyListenPort' in endpoint_source
    assert '`${window.location.origin}/grpc`' in endpoint_source


def test_envoy_entry_uses_networking_category_and_proxy_label() -> None:
    """Envoy appears as a networking proxy in Apps."""
    envoy = _import_envoy()

    assert envoy.ENTRY.label == 'Envoy proxy'
    assert envoy.ENTRY.category == 'Networking'


async def test_prepare_envoy_includes_native_listener_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When gRPC Access is on, Envoy renders the native-gRPC TCP listener."""
    envoy = _import_envoy()
    config_path = tmp_path / 'envoy.yaml'
    monkeypatch.setattr(envoy, 'ENVOY_CONFIG_PATH', config_path)
    monkeypatch.setattr(envoy, '_grpc_remote_access', lambda: True)

    assert await envoy.prepare_envoy()

    config = config_path.read_text()
    assert 'name: grpc_native_listener' in config
    assert 'port_value: 50053' in config
    assert 'tcp_proxy' in config
    # Forwards to the existing core-gRPC cluster, untouched grpc-web listener.
    assert 'cluster: grpc_service_cluster' in config


async def test_prepare_envoy_omits_native_listener_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When gRPC Access is off, the native listener is absent."""
    envoy = _import_envoy()
    config_path = tmp_path / 'envoy.yaml'
    monkeypatch.setattr(envoy, 'ENVOY_CONFIG_PATH', config_path)
    monkeypatch.setattr(envoy, '_grpc_remote_access', lambda: False)

    assert await envoy.prepare_envoy()

    config = config_path.read_text()
    assert 'grpc_native_listener' not in config
    assert 'port_value: 50053' not in config
    # The grpc-web listener is still present regardless.
    assert 'port_value: 50052' in config
