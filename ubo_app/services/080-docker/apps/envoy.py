"""Envoy gRPC proxy Docker app."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, cast

from apps._registry import ContainerEntry
from ubo_app.constants import GRPC_ENVOY_LISTEN_PORT, GRPC_LISTEN_PORT
from ubo_app.utils import IS_RPI

ENVOY_TEMPLATE_PATH = Path(__file__).parent.parent / 'assets' / 'envoy.yaml.tmpl'
ENVOY_CONFIG_PATH = Path(__file__).parent.parent / 'assets' / 'envoy.yaml'


async def prepare_envoy() -> bool:
    """Prepare Envoy for gRPC."""
    process = await asyncio.create_subprocess_exec(
        '/usr/bin/env',
        'envsubst',
        env={
            'GRPC_ENVOY_LISTEN_PORT': f'{GRPC_ENVOY_LISTEN_PORT}',
            'GRPC_LISTEN_PORT': f'{GRPC_LISTEN_PORT}',
            'GRPC_SERVER_HOST': '127.0.0.1' if IS_RPI else 'host.docker.internal',
            **os.environ,
        },
        stdin=ENVOY_TEMPLATE_PATH.open(),
        stdout=ENVOY_CONFIG_PATH.open('w'),
    )
    await process.wait()
    return process.returncode == 0


ENTRY = ContainerEntry(
    id='envoy_grpc',
    label='Envoy for gRPC',
    icon='󱂇',
    path='thegrandpkizzle/envoy:1.26.1',
    prepare=prepare_envoy,
    command=['--config-path', 'envoy.yaml'],
    registry='docker.io',
    volumes=[
        f'{ENVOY_CONFIG_PATH}:/envoy.yaml',
    ],
    **cast(
        'Any',
        {'network_mode': 'host'}
        if IS_RPI
        else {
            'ports': {
                f'{GRPC_ENVOY_LISTEN_PORT}/tcp': GRPC_ENVOY_LISTEN_PORT,
            },
        },
    ),
)
