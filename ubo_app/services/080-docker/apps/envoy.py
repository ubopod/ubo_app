"""Envoy gRPC proxy Docker app."""

from __future__ import annotations

from pathlib import Path
from string import Template

from apps._registry import ContainerEntry
from ubo_app.constants import (
    GRPC_ENVOY_LISTEN_PORT,
    GRPC_LISTEN_PORT,
    WEB_UI_LISTEN_PORT,
)
from ubo_app.utils import IS_RPI

ENVOY_TEMPLATE_PATH = Path(__file__).parent.parent / 'assets' / 'envoy.yaml.tmpl'
ENVOY_CONFIG_PATH = Path(__file__).parent.parent / 'assets' / 'envoy.yaml'


async def prepare_envoy() -> bool:
    """Prepare Envoy for gRPC."""
    server_host = '127.0.0.1' if IS_RPI else 'host.docker.internal'
    rendered = Template(ENVOY_TEMPLATE_PATH.read_text()).substitute(
        GRPC_ENVOY_LISTEN_PORT=f'{GRPC_ENVOY_LISTEN_PORT}',
        GRPC_LISTEN_PORT=f'{GRPC_LISTEN_PORT}',
        GRPC_SERVER_HOST=server_host,
        WEB_UI_LISTEN_PORT=f'{WEB_UI_LISTEN_PORT}',
        WEB_UI_SERVER_HOST=server_host,
    )
    ENVOY_CONFIG_PATH.write_text(rendered)
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
    },
    volumes=[
        f'{ENVOY_CONFIG_PATH}:/envoy.yaml',
    ],
)
