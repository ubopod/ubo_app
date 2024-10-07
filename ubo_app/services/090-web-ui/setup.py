"""Implementation of the web-ui service."""

import asyncio
from pathlib import Path

from quart import Quart
from redux import FinishEvent

from ubo_app.constants import WEB_UI_DEBUG_MODE, WEB_UI_LISTEN_HOST, WEB_UI_LISTEN_PORT
from ubo_app.store.main import store


async def init_service() -> None:
    """Initialize the web-ui service."""
    app = Quart('ubo-app')
    app.debug = False
    shutdown_event: asyncio.Event = asyncio.Event()

    @app.get('/')
    async def hello_world() -> str:
        return (Path(__file__).parent / 'static' / 'index.html').read_text()

    store.subscribe_event(FinishEvent, shutdown_event.set)

    async def wait_for_shutdown() -> None:
        await shutdown_event.wait()

    await app.run_task(
        host=WEB_UI_LISTEN_HOST,
        port=WEB_UI_LISTEN_PORT,
        debug=WEB_UI_DEBUG_MODE,
        shutdown_trigger=wait_for_shutdown,
    )
