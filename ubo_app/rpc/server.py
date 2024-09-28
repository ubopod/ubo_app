# ruff: noqa: N802
"""gRPC server for the store service."""

from __future__ import annotations

from grpclib.reflection.service import ServerReflection
from grpclib.server import Server

from ubo_app.logging import logger
from ubo_app.rpc.service import StoreService

LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 50051


async def serve() -> None:
    """Serve the gRPC server."""
    services = [StoreService()]
    services = ServerReflection.extend(services)

    server = Server(services)

    logger.error(
        'Starting gRPC server',
        extra={'host': LISTEN_HOST, 'port': LISTEN_PORT},
    )
    await server.start(LISTEN_HOST, LISTEN_PORT)

    await server.wait_closed()
