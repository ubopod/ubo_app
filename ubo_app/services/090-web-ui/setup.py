"""Implementation of the web-ui service."""

import asyncio
import datetime
import functools
import re
import socket
from pathlib import Path
from typing import cast

from quart import Quart, render_template, request
from redux import FinishEvent
from werkzeug.datastructures import FileStorage

from ubo_app.constants import (
    WEB_UI_DEBUG_MODE,
    WEB_UI_HOTSPOT_PASSWORD,
    WEB_UI_LISTEN_ADDRESS,
    WEB_UI_LISTEN_PORT,
)
from ubo_app.logger import logger
from ubo_app.store.input.types import (
    InputCancelAction,
    InputDescription,
    InputMethod,
    InputProvideAction,
    InputResult,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.voice import ReadableInformation
from ubo_app.store.services.web_ui import WebUIInitializeEvent, WebUIStopEvent
from ubo_app.utils.network import has_gateway
from ubo_app.utils.pod_id import get_pod_id
from ubo_app.utils.server import send_command


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
        result = await send_command('hotspot', 'start', has_output=True)
        if result != 'done':
            store.dispatch(
                InputCancelAction(id=event.description.id),
                NotificationsAddAction(
                    notification=Notification(
                        id='web_ui:hotspot_error',
                        icon='󱋆',
                        title='Web UI Error',
                        content='Failed to start the hotspot, please check the logs.',
                        display_type=NotificationDisplayType.STICKY,
                        importance=Importance.HIGH,
                    ),
                ),
            )
            return
    hostname = socket.gethostname()
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
                        else f'Please connect to the "{get_pod_id()}" WiFi network '
                        f'with password "{WEB_UI_HOTSPOT_PASSWORD}" and open '
                        f'http://{hostname}.local:{WEB_UI_LISTEN_PORT} in your browser.'
                    ),
                ),
                expiration_timestamp=datetime.datetime.now(tz=datetime.UTC),
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
    result = await send_command('hotspot', 'stop', has_output=True)
    if result != 'done':
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='web_ui:hotspot_error',
                    icon='󱋆',
                    title='Web UI Error',
                    content='Failed to stop the hotspot property, '
                    'please check the logs.',
                    display_type=NotificationDisplayType.STICKY,
                    importance=Importance.HIGH,
                ),
            ),
        )


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
                        result=InputResult(
                            data=data,
                            files=files,
                            method=InputMethod.WEB_DASHBOARD,
                        ),
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
