"""Implementation of the web-ui service."""

import asyncio
import re
from pathlib import Path

from quart import Quart, render_template, request
from redux import FinishEvent

from ubo_app.constants import WEB_UI_DEBUG_MODE, WEB_UI_LISTEN_HOST, WEB_UI_LISTEN_PORT
from ubo_app.store.main import store
from ubo_app.store.operations import (
    InputCancelAction,
    InputDescription,
    InputProvideAction,
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
            if data['action'] == 'cancel':
                store.dispatch(InputCancelAction(id=data['id']))
            elif data['action'] == 'provide':
                id = data.pop('id')
                value = data.pop('value', '')
                store.dispatch(
                    InputProvideAction(
                        id=id,
                        value=value,
                        data=data,
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

    async def wait_for_shutdown() -> None:
        await shutdown_event.wait()

    await app.run_task(
        host=WEB_UI_LISTEN_HOST,
        port=WEB_UI_LISTEN_PORT,
        debug=WEB_UI_DEBUG_MODE,
        shutdown_trigger=wait_for_shutdown,
    )
