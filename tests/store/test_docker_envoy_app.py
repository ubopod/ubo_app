"""Tests for the Envoy Docker app."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    import pytest


DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'
WEB_APP_CLIENT_PATH = (
    Path(__file__).parents[2]
    / 'ubo_app'
    / 'services'
    / '090-web-ui'
    / 'web-app'
    / 'src'
    / 'client.tsx'
)


class EnvoyModule(Protocol):
    """Protocol for the Envoy module members used by these tests."""

    ENVOY_CONFIG_PATH: Path
    ENVOY_TEMPLATE_PATH: Path

    async def prepare_envoy(self) -> bool:
        """Prepare Envoy configuration."""
        ...


def _import_envoy() -> EnvoyModule:
    """Import the Envoy module as the Docker service would."""
    if str(DOCKER_SERVICE_PATH) not in sys.path:
        sys.path.insert(0, str(DOCKER_SERVICE_PATH))

    return cast('EnvoyModule', import_module('apps.envoy'))


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
    assert 'address: host.docker.internal' in config
    assert 'port_value: 4321' in config
    assert 'name: grpc_service_cluster' in config
    assert "prefix: '/grpc/'" in config
    assert "prefix_rewrite: '/'" in config
    assert config.index("prefix: '/grpc/'") < config.index("prefix: '/'")


def test_web_ui_grpc_client_uses_same_origin_grpc_path() -> None:
    """The browser client routes gRPC-web through Envoy."""
    client_source = WEB_APP_CLIENT_PATH.read_text()

    assert 'window.location.port === window.WEB_UI_CONFIG.webUiListenPort' in (
        client_source
    )
    assert 'window.WEB_UI_CONFIG.grpcEnvoyListenPort' in client_source
    assert '`${window.location.origin}/grpc`' in client_source
