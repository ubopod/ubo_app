"""gRPC server for the store service."""

from __future__ import annotations

from grpclib.reflection.service import ServerReflection
from grpclib.server import Server
from ubo_app.constants import GRPC_LISTEN_ADDRESS, GRPC_LISTEN_PORT
from ubo_app.logger import logger
from ubo_app.rpc.secrets_service import SecretsService
from ubo_app.rpc.store_service import StoreService

_server_container: list[Server | None] = [None]


def get_server() -> Server | None:
    """Get the current gRPC server instance."""
    return _server_container[0]


async def close_server() -> None:
    """Close the gRPC server if running."""
    server = _server_container[0]
    if server is not None:
        server.close()
        await server.wait_closed()
        _server_container[0] = None


async def serve() -> None:
    """Serve the gRPC server."""
    services = [StoreService(), SecretsService()]
    services = ServerReflection.extend(services)

    server = Server(services)
    _server_container[0] = server

    logger.info(
        'Starting gRPC server',
        extra={'host': GRPC_LISTEN_ADDRESS, 'port': GRPC_LISTEN_PORT},
    )
    await server.start(GRPC_LISTEN_ADDRESS, GRPC_LISTEN_PORT)

    await server.wait_closed()
