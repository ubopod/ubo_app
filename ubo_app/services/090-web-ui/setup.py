"""Implementation of the web-ui service."""

import asyncio
import datetime
import functools
import re
import socket
import subprocess
from pathlib import Path
from typing import cast

from quart import Quart, render_template, request
from redux import FinishEvent
from werkzeug.datastructures import FileStorage

from ubo_app.constants import (
    WEB_UI_DEBUG_MODE,
    WEB_UI_LISTEN_ADDRESS,
    WEB_UI_LISTEN_PORT,
)
from ubo_app.logger import logger
from ubo_app.store.input.types import (
    InputCancelAction,
    InputDescription,
    InputProvideAction,
    InputResult,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.voice import ReadableInformation
from ubo_app.store.services.web_ui import WebUIInitializeEvent, WebUIStopEvent
from ubo_app.utils.server import send_command


async def has_gateway() -> bool:
    """Check if any network is connected."""
    try:
        # macOS uses 'route -n get default', Linux uses 'ip route'
        process = await asyncio.create_subprocess_exec(
            'which',
            'ip',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        await process.wait()
        if process.returncode == 0:
            # For Linux
            process = await asyncio.create_subprocess_exec(
                'ip',
                'route',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            await process.wait()
            if process.returncode == 0 and process.stdout:
                for line in (await process.stdout.read()).splitlines():
                    if line.startswith(b'default'):
                        return True
        else:
            # For macOS
            process = await asyncio.create_subprocess_exec(
                'route',
                '-n',
                'get',
                'default',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            await process.wait()
            if process.returncode == 0 and process.stdout:
                for line in (await process.stdout.read()).splitlines():
                    if b'gateway:' in line:
                        return True
    finally:
        pass
    return False


async def initialize(event: WebUIInitializeEvent) -> None:
    """Start the hotspot if there is no network connection."""
    is_connected = await has_gateway()
    logger.info(
        'web-ui - initialize',
        extra={
            'is_connected': is_connected,
            'description': event.description,
        },
    )
    if not is_connected:
        await send_command('hotspot', 'start')
    hostname = socket.gethostname()
    if event.description:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=f'web_ui:pending:{event.description.id}',
                    icon='󱋆',
                    title='Web UI',
                    content=f'[size=18dp]{event.description.prompt}[/size]',
                    display_type=NotificationDisplayType.STICKY,
                    is_read=True,
                    extra_information=ReadableInformation(
                        text=(
                            'Please make sure you are on the same network as this '
                            f'ubo-pod and open http://{hostname}.local:{WEB_UI_LISTEN_PORT}'
                            'in your browser.'
                            if is_connected
                            else 'Please connect to the "UBO" WiFi network and open '
                            f'http://{hostname}.local:{WEB_UI_LISTEN_PORT} in your '
                            'browser.'
                        ),
                    ),
                    expiration_timestamp=datetime.datetime.now(tz=datetime.UTC),
                    color='#ffffff',
                    show_dismiss_action=False,
                    dismiss_on_close=True,
                    on_close=functools.partial(
                        store.dispatch,
                        InputCancelAction(id=event.description.id),
                    ),
                ),
            ),
        )


async def stop() -> None:
    """Start the hotspot if there is no network connection."""
    logger.info('web-ui - stop')
    await send_command('hotspot', 'stop')


async def init_service() -> None:
    """Initialize the web-ui service."""
    _ = []
    app = Quart(
        'ubo-app',
        template_folder=(Path(__file__).parent / 'templates').absolute().as_posix(),
    )
    app.debug = WEB_UI_DEBUG_MODE
    shutdown_event: asyncio.Event = asyncio.Event()

    @store.view(lambda state: state.web_ui.active_inputs)
    def inputs(inputs: list[InputDescription]) -> list[InputDescription]:
        return inputs

    @app.route('/', methods=['GET', 'POST'])
    async def inputs_form() -> str:
        if request.method == 'POST':
            data = dict(await request.form)
            files = {
                key: cast(FileStorage, value).stream
                for key, value in (await request.files).items()
            }

            if data['action'] == 'cancel':
                store.dispatch(InputCancelAction(id=data['id']))
            elif data['action'] == 'provide':
                id = data.pop('id')
                value = data.pop('value', '')
                store.dispatch(
                    InputProvideAction(
                        id=id,
                        value=value,
                        result=InputResult(data=data, files=files),
                    ),
                )
            await asyncio.sleep(0.2)
        return await render_template('index.jinja2', inputs=inputs(), re=re)

    _.append(inputs_form)

    if WEB_UI_DEBUG_MODE:

        @app.errorhandler(Exception)
        async def handle_error(_: Exception) -> str:
            import traceback

            return f'<pre>{traceback.format_exc()}</pre>'

        _.append(handle_error)

    store.subscribe_event(FinishEvent, shutdown_event.set)

    store.subscribe_event(WebUIInitializeEvent, initialize)
    store.subscribe_event(WebUIStopEvent, stop)

    async def wait_for_shutdown() -> None:
        await shutdown_event.wait()

    await app.run_task(
        host=WEB_UI_LISTEN_ADDRESS,
        port=WEB_UI_LISTEN_PORT,
        debug=WEB_UI_DEBUG_MODE,
        shutdown_trigger=wait_for_shutdown,
    )
