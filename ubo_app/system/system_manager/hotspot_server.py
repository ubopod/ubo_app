"""A simple DNS server that responds to all queries with a fixed A record."""

from __future__ import annotations

import asyncio

from quart import Quart, request

from ubo_app.constants import (
    WEB_UI_DEBUG_MODE,
    WEB_UI_LISTEN_PORT,
)
from ubo_app.logger import get_logger

logger = get_logger('system-manager')

CAPTIVE_IP = '192.168.4.1'  # The IP your machine will have on its Wi-Fi AP interface
PORT_HTTP = WEB_UI_LISTEN_PORT  # The port for the HTTP server

REDIRECT_PATHS = [
    '/generate_204',  # Android captive check
    '/hotspot-detect.html',  # Apple captive check
    '/canonical.html',  # Firefox captive check
    '/ncsi.txt',  # Windows captive check
    '/redirect',  # Microsoft variant
    '/connecttest.txt',  # Windows 11 variant
]

shutdown_event: asyncio.Event | None = None


async def start_redirect_server() -> None:
    """Start the HTTP server that will redirect all requests to the web UI."""
    global shutdown_event  # noqa: PLW0603
    if shutdown_event:
        return
    shutdown_event = asyncio.Event()

    app = Quart('ubo-app-redirect-server')
    app.debug = WEB_UI_DEBUG_MODE

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    async def _(path: str) -> tuple[str, int, dict[str, str]]:
        if request.path in REDIRECT_PATHS:
            logger.info('Redirecting to the web UI...', extra={'path': path})
            return '', 302, {'Location': f'http://{CAPTIVE_IP}:{PORT_HTTP}/'}

        if request.path == '/favicon.ico':
            return '', 404, {}

        return '', 302, {'Location': f'http://{CAPTIVE_IP}:{PORT_HTTP}/'}

    async def wait_for_shutdown() -> None:
        if shutdown_event:
            await shutdown_event.wait()

    await app.run_task(
        host='0.0.0.0',  # noqa: S104
        port=80,
        debug=WEB_UI_DEBUG_MODE,
        shutdown_trigger=wait_for_shutdown,
    )


def stop_redirect_server() -> None:
    """Stop the HTTP server."""
    global shutdown_event  # noqa: PLW0603
    if shutdown_event:
        shutdown_event.set()
        shutdown_event = None
