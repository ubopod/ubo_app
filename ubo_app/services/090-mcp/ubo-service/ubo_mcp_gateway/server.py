"""HTTP server exposing the aggregated MCP gateway over SSE + Streamable HTTP.

FastMCP has no way to remove a backend from a running proxy, so on every change
to the enabled-server set the proxy (and its ASGI apps) are rebuilt and the
uvicorn server is restarted on a *persistent* listening socket — the listener
never closes, so the endpoint stays bound while the tool set updates.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from typing import TYPE_CHECKING, Any

import uvicorn
from fastmcp import FastMCP
from fastmcp.server import create_proxy
from loguru import logger
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount

from ubo_mcp_gateway.gateway import build_mcp_config, extract_items

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from ubo_bindings.client import UboRPCClient

ASGIApp = Any


class _BearerAuthMiddleware:
    """Reject requests lacking the gateway bearer token.

    Pure ASGI middleware (not ``BaseHTTPMiddleware``) so it does not buffer the
    streaming SSE / Streamable-HTTP responses.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        """Wrap ``app``, requiring ``Bearer {token}`` on every HTTP request."""
        self.app = app
        self._expected = f'Bearer {token}'.encode()

    async def __call__(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get('headers', []))
        if headers.get(b'authorization', b'') != self._expected:
            await send({
                'type': 'http.response.start',
                'status': 401,
                'headers': [(b'content-type', b'text/plain')],
            })
            await send({'type': 'http.response.body', 'body': b'Unauthorized'})
            return

        await self.app(scope, receive, send)


def build_app(config: dict[str, Any], token: str) -> Starlette:
    """Build the parent ASGI app exposing both transports for ``config``."""
    if config.get('mcpServers'):
        proxy: FastMCP = create_proxy(config)
    else:
        # Empty config: serve a valid but tool-less gateway rather than crash.
        proxy = FastMCP('ubo-mcp-gateway')

    streamable_app = proxy.http_app(transport='streamable-http', path='/')
    sse_app = proxy.http_app(transport='sse', path='/')

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with (
            streamable_app.router.lifespan_context(streamable_app),
            sse_app.router.lifespan_context(sse_app),
        ):
            yield

    return Starlette(
        routes=[
            Mount('/mcp', app=streamable_app),
            Mount('/sse', app=sse_app),
        ],
        lifespan=lifespan,
        middleware=[Middleware(_BearerAuthMiddleware, token=token)],
    )


class GatewayServer:
    """Owns the persistent socket and rebuilds the app on config changes."""

    def __init__(
        self,
        *,
        client: UboRPCClient,
        token: str,
        host: str,
        port: int,
    ) -> None:
        """Initialize the gateway server bound to ``host``:``port``."""
        self._client = client
        self._token = token
        self._host = host
        self._port = port
        self._desired_config: dict[str, Any] = {'mcpServers': {}}
        self._current_config: dict[str, Any] | None = None
        self._restart_event = asyncio.Event()

    def _on_servers_change(self, data: list) -> None:
        """Autorun callback (runs on the client event loop)."""
        try:
            config = build_mcp_config(extract_items(data))
        except Exception:
            logger.exception('Failed to build MCP config from store update')
            return
        if config != self._desired_config:
            self._desired_config = config
            self._restart_event.set()

    async def serve(self) -> None:
        """Run the gateway until cancelled, restarting on config changes."""
        self._client.autorun([
            'state.mcp.enabled_mcp_servers_with_metadata',
        ])(self._on_servers_change)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, self._port))
        sock.listen()
        logger.info(
            'MCP gateway listening {extra}',
            extra={'host': self._host, 'port': self._port},
        )

        try:
            while True:
                self._restart_event.clear()
                self._current_config = self._desired_config
                app = build_app(self._current_config, self._token)
                server = uvicorn.Server(
                    uvicorn.Config(
                        app,
                        log_level='warning',
                        lifespan='on',
                    ),
                )
                # Hand uvicorn a *duplicate* fd each cycle: uvicorn closes the
                # sockets it is given on shutdown, so passing the original would
                # kill the listener after the first rebuild. The dup closes
                # while the persistent `sock` stays bound.
                serve_task = asyncio.create_task(
                    server.serve(sockets=[sock.dup()]),
                )

                # Wait until the enabled set changes, then cycle the server.
                await self._restart_event.wait()
                logger.info('MCP server set changed; rebuilding gateway')
                server.should_exit = True
                await serve_task
        finally:
            sock.close()
