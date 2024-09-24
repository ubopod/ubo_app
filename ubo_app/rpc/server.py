# ruff: noqa: N802
"""gRPC server for the store service."""

from __future__ import annotations

from grpclib.server import Server

from ubo_app.logging import logger
from ubo_app.rpc.service import StoreService

LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 50051


async def serve() -> None:
    """Serve the gRPC server."""
    server = Server([StoreService()])

    logger.error(
        'Starting gRPC server',
        extra={'host': LISTEN_HOST, 'port': LISTEN_PORT},
    )
    await server.start(LISTEN_HOST, LISTEN_PORT)

    await server.wait_closed()
