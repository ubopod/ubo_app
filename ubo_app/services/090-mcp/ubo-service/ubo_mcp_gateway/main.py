"""Entry point for the ubo MCP gateway subprocess.

Connects to ubo-app's gRPC store, reads the gateway bearer token, then serves
the aggregated MCP endpoint over SSE + Streamable HTTP.
"""

from __future__ import annotations

import asyncio
import os

from loguru import logger
from ubo_bindings.client import UboRPCClient

from ubo_mcp_gateway.logging import setup_file_logging
from ubo_mcp_gateway.server import GatewayServer

DEFAULT_LISTEN_ADDRESS = '0.0.0.0'  # noqa: S104
DEFAULT_LISTEN_PORT = 4322


async def _run() -> None:
    client = UboRPCClient('localhost', 50051)

    token = await client.query_secret(
        os.environ['MCP_GATEWAY_TOKEN_SECRET_ID'],
        default='',
    )
    if not token:
        logger.error('No MCP gateway token configured; refusing to start')
        return

    host = os.environ.get('MCP_GATEWAY_LISTEN_ADDRESS', DEFAULT_LISTEN_ADDRESS)
    port = int(os.environ.get('MCP_GATEWAY_LISTEN_PORT', str(DEFAULT_LISTEN_PORT)))

    server = GatewayServer(client=client, token=token, host=host, port=port)
    try:
        await server.serve()
    finally:
        client.close()


def main() -> None:
    """Run the MCP gateway subprocess."""
    setup_file_logging()
    logger.info('Starting ubo MCP gateway')
    asyncio.run(_run())


if __name__ == '__main__':
    main()
