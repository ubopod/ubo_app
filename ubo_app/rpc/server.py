# ruff: noqa: N802
"""gRPC server for the store service."""

from __future__ import annotations

from grpclib.reflection.service import ServerReflection
from grpclib.server import Server

from ubo_app.constants import GRPC_LISTEN_HOST, GRPC_LISTEN_PORT
from ubo_app.logging import logger
from ubo_app.rpc.service import StoreService


async def serve() -> None:
    """Serve the gRPC server."""
    services = [StoreService()]
    services = ServerReflection.extend(services)

    server = Server(services)

    logger.info(
        'Starting gRPC server',
        extra={'host': GRPC_LISTEN_HOST, 'port': GRPC_LISTEN_PORT},
    )
    await server.start(GRPC_LISTEN_HOST, GRPC_LISTEN_PORT)

    await server.wait_closed()
