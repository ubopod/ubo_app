"""Envoy gRPC proxy Docker app."""

from __future__ import annotations

from pathlib import Path
from string import Template

from apps._registry import ContainerEntry
from ubo_app.constants import (
    CONFIG_PATH,
    GRPC_ENVOY_LISTEN_PORT,
    GRPC_LISTEN_PORT,
    GRPC_NATIVE_PROXY_LISTEN_PORT,
    WEB_UI_LISTEN_PORT,
)
from ubo_app.store.main import store
from ubo_app.utils import IS_RPI

ENVOY_TEMPLATE_PATH = Path(__file__).parent.parent / 'assets' / 'envoy.yaml.tmpl'
# Render the config under ``CONFIG_PATH`` (``~/.config/ubo``), NOT inside the
# versioned install tree (``/opt/ubo/<version>/…``). The installer runs
# ``chmod -R 700 /opt/ubo`` on every update, which makes a config rendered there
# unreadable to the container's non-root ``envoy`` user, and the versioned path
# also changes on every version bump — both leave the reused container bound to a
# stale/unreadable config and stuck in a crash loop. ``CONFIG_PATH`` is stable
# across versions and untouched by that chmod, matching how every other Docker
# app (Hermes, Home Assistant, Node-RED) stores its runtime config.
ENVOY_CONFIG_PATH = CONFIG_PATH / 'envoy' / 'envoy.yaml'
# Raw TCP-proxy listener that forwards native gRPC traffic to the loopback-only
# core server. Rendered into the config only while the "gRPC Access" setting is
# on, exposing the native API on the LAN at 0.0.0.0:GRPC_NATIVE_PROXY_LISTEN_PORT.
NATIVE_LISTENER_TEMPLATE_PATH = (
    Path(__file__).parent.parent / 'assets' / 'envoy-native-listener.yaml.tmpl'
)


@store.with_state(lambda state: state.settings.grpc_remote_access)
def _grpc_remote_access(grpc_remote_access: bool) -> bool:  # noqa: FBT001
    return grpc_remote_access


async def prepare_envoy() -> bool:
    """Prepare Envoy for gRPC."""
    server_host = '127.0.0.1' if IS_RPI else 'host.docker.internal'
    native_listener = (
        Template(NATIVE_LISTENER_TEMPLATE_PATH.read_text()).substitute(
            GRPC_NATIVE_PROXY_LISTEN_PORT=f'{GRPC_NATIVE_PROXY_LISTEN_PORT}',
        )
        if _grpc_remote_access()
        else ''
    )
    rendered = Template(ENVOY_TEMPLATE_PATH.read_text()).substitute(
        GRPC_ENVOY_LISTEN_PORT=f'{GRPC_ENVOY_LISTEN_PORT}',
        GRPC_LISTEN_PORT=f'{GRPC_LISTEN_PORT}',
        GRPC_SERVER_HOST=server_host,
        WEB_UI_LISTEN_PORT=f'{WEB_UI_LISTEN_PORT}',
        WEB_UI_SERVER_HOST=server_host,
        GRPC_NATIVE_LISTENER=native_listener,
    )
    ENVOY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENVOY_CONFIG_PATH.write_text(rendered)
    # The container drops to its non-root ``envoy`` user (uid 100) before reading
    # the bind-mounted config, so it must stay world-readable regardless of the
    # rendering process's umask. The rendered config holds no secrets (only ports
    # and hosts).
    ENVOY_CONFIG_PATH.chmod(0o644)
    return True


ENTRY = ContainerEntry(
    id='envoy_grpc',
    label='Envoy proxy',
    icon='󱂇',
    path='thegrandpkizzle/envoy:1.26.1',
    prepare=prepare_envoy,
    command=['--config-path', 'envoy.yaml'],
    registry='docker.io',
    category='Networking',
    network_mode='host' if IS_RPI else 'bridge',
    ports={}
    if IS_RPI
    else {
        f'{GRPC_ENVOY_LISTEN_PORT}/tcp': GRPC_ENVOY_LISTEN_PORT,
        f'{GRPC_NATIVE_PROXY_LISTEN_PORT}/tcp': GRPC_NATIVE_PROXY_LISTEN_PORT,
    },
    volumes=[
        f'{ENVOY_CONFIG_PATH}:/envoy.yaml',
    ],
)
