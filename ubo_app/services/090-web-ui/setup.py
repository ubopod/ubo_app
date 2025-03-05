"""Implementation of the web-ui service."""

import asyncio
import datetime
import functools
import json
import re
from pathlib import Path
from typing import Literal, cast

from quart import Quart, Response, render_template, request
from redux import FinishEvent
from werkzeug.datastructures import FileStorage

from ubo_app.constants import (
    GRPC_ENVOY_LISTEN_PORT,
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
from ubo_app.store.main import UboStore, store
from ubo_app.store.services.docker import (
    DockerImageFetchAction,
    DockerImageRemoveAction,
    DockerImageRemoveContainerAction,
    DockerImageRunContainerAction,
    DockerImageStopContainerAction,
    DockerInstallAction,
    DockerStartAction,
    DockerStopAction,
)
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

ENVOY_IMAGE_NAME = 'thegrandpkizzle/envoy:1.26.1'


async def _get_docker_status() -> str:
    try:
        process = await asyncio.subprocess.create_subprocess_exec(
            'docker',
            'info',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.wait(), timeout=2)
        if process.returncode is None:
            process.kill()
        if process.stdout and process.returncode == 0:
            output = await process.stdout.read()
            return 'running' if 'Containers' in output.decode() else 'not ready'
    except FileNotFoundError:
        logger.warning('Docker is not installed')
        return 'not installed'
    except Exception:
        logger.exception('Failed to check if docker is running')
        return 'failed'
    else:
        logger.warning('Docker process returned non-zero exit code')
        return 'not running'


async def _get_envoy_status() -> str:
    try:
        process = await asyncio.subprocess.create_subprocess_exec(
            'docker',
            'inspect',
            ENVOY_IMAGE_NAME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.wait(), timeout=2)
        if process.returncode is None:
            process.kill()
        if process.stdout and process.returncode == 0:
            output = await process.stdout.read()
            if ENVOY_IMAGE_NAME in output.decode():
                process = await asyncio.subprocess.create_subprocess_exec(
                    'docker',
                    'ps',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(process.wait(), timeout=3)
                if process.returncode is None:
                    process.kill()
                if process.stdout and process.returncode == 0:
                    output = await process.stdout.read()
                    return (
                        'running'
                        if ENVOY_IMAGE_NAME in output.decode()
                        else 'not running'
                    )

                logger.warning('Docker process returned non-zero exit code')
                return 'not running'

            return 'not running'
        else:  # noqa: RET505
            logger.warning('Docker process returned non-zero exit code')
            return 'not downloaded'
    except Exception:
        logger.exception('Failed to check if envoy is running')
        return 'failed'


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
                        'ubo-pod and open '
                        f'http://{{{{hostname}}}}:{WEB_UI_LISTEN_PORT} in your browser.'
                        if is_connected
                        else f'Please connect to the "{get_pod_id()}" WiFi network '
                        f'with password "{WEB_UI_HOTSPOT_PASSWORD}" and open '
                        f'http://{{{{hostname}}}}:{WEB_UI_LISTEN_PORT} in your browser.'
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


async def init_service() -> None:  # noqa: C901
    """Initialize the web-ui service."""
    _ = []
    app = Quart(
        'ubo-app',
        template_folder=(Path(__file__).parent / 'templates').absolute().as_posix(),
        static_folder=(Path(__file__).parent / 'web-app' / 'dist')
        .absolute()
        .as_posix(),
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
        return await render_template(
            'index.jinja2',
            inputs=UboStore.serialize_value(inputs()),
            re=re,
            GRPC_ENVOY_LISTEN_PORT=GRPC_ENVOY_LISTEN_PORT,
        )

    @app.route('/status')
    async def status() -> Response:
        statuses = await asyncio.gather(
            _get_docker_status(),
            _get_envoy_status(),
        )
        return Response(
            json.dumps(
                {
                    'status': 'ok',
                    'docker': statuses[0],
                    'envoy': statuses[1],
                    'inputs': UboStore.serialize_value(inputs()),
                },
            ),
            content_type='application/json',
        )

    @app.route('/action/', methods=['POST'])
    async def action() -> Response:
        data = await request.json
        action: Literal[
            'install docker',
            'run docker',
            'stop docker',
            'download envoy',
            'run envoy',
            'remove envoy',
        ] = data['action']
        if action == 'install docker':
            store.dispatch(DockerInstallAction())
        elif action == 'run docker':
            store.dispatch(DockerStartAction())
        elif action == 'stop docker':
            store.dispatch(DockerStopAction())
        elif action == 'download envoy':
            store.dispatch(DockerImageFetchAction(image='envoy_grpc'))
        elif action == 'run envoy':
            store.dispatch(DockerImageRunContainerAction(image='envoy_grpc'))
        elif action == 'remove envoy':
            store.dispatch(DockerImageStopContainerAction(image='envoy_grpc'))
            await asyncio.sleep(2)
            store.dispatch(DockerImageRemoveContainerAction(image='envoy_grpc'))
            await asyncio.sleep(2)
            store.dispatch(DockerImageRemoveAction(image='envoy_grpc'))
        return Response(
            json.dumps({'status': 'ok'}),
            content_type='application/json',
        )

    _.extend([inputs_form, status, action])

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
