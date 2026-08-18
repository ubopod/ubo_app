"""Implementation of the web-ui service."""

import asyncio
import functools
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from uuid import uuid4

from quart import Quart, Response, render_template, request, send_file
from ubo_bindings.ubo.v1 import WebUiState as GRPCWebUIState

from ubo_app.constants import (
    GRPC_ENVOY_LISTEN_PORT,
    WEB_UI_DEBUG_MODE,
    WEB_UI_HOTSPOT_PASSWORD,
    WEB_UI_LISTEN_ADDRESS,
    WEB_UI_LISTEN_PORT,
)
from ubo_app.logger import logger
from ubo_app.rpc.object_to_message import build_message
from ubo_app.store.core.bindable_actions import register_bindable_action
from ubo_app.store.core.callback_registry import register_auto_callback
from ubo_app.store.core.types import (
    OpenRenderAction,
    StackPopAction,
)
from ubo_app.store.input.types import (
    InputCancelAction,
    InputMethod,
    InputProvideAction,
    InputResult,
)
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageFetchAction,
    DockerImageRemoveAction,
    DockerImageRemoveContainerAction,
    DockerImageRunAction,
    DockerImageStopAction,
    DockerInstallAction,
    DockerStartAction,
    DockerStopAction,
)
from ubo_app.store.services.file_upload import (
    FileUploadChunkAction,
    FileUploadCompleteAction,
    FileUploadStartAction,
)
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearEvent,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.services.web_ui import (
    WebUIInitializeEvent,
    WebUIInputAction,
    WebUIInputCommand,
    WebUIState,
)
from ubo_app.store.services.wifi import WiFiStartHotspotAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.hotspot_qr import hotspot_qr_action, pop_hotspot_qr_render
from ubo_app.utils.network import has_gateway
from ubo_app.utils.pod_id import get_pod_id
from ubo_app.utils.types import Subscriptions

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage

ENVOY_IMAGE_NAME = 'thegrandpkizzle/envoy:1.26.1'

# Cache bust key based on main.js mtime to force browser reload after rebuilds
_dist_js = Path(__file__).parent / 'web-app' / 'dist' / 'main.js'
_cache_bust = str(int(_dist_js.stat().st_mtime)) if _dist_js.exists() else '0'


# Status cache: maps key -> (timestamp, result)
_status_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 5.0


_DOCKER_COMMAND_TIMEOUT = 5.0

# Browser uploads are re-chunked onto the same store path gRPC clients use, so
# the file-system service sees one code path regardless of where the bytes came
# from.
UPLOAD_CHUNK_SIZE = 1024 * 1024


async def _run_docker_command(
    *args: str,
) -> tuple[int | None, str]:
    """Run a docker command with timeout, killing the process on timeout."""
    process = await asyncio.subprocess.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=_DOCKER_COMMAND_TIMEOUT)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    output = ''
    if process.stdout and process.returncode == 0:
        output = (await process.stdout.read()).decode()
    return process.returncode, output


async def _get_docker_status() -> str:
    cached = _status_cache.get('docker')
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    result = await _get_docker_status_uncached()
    _status_cache['docker'] = (time.time(), result)
    return result


async def _get_docker_status_uncached() -> str:
    try:
        returncode, output = await _run_docker_command('docker', 'info')
        if returncode == 0:
            return 'running' if 'Containers' in output else 'not ready'
    except FileNotFoundError:
        logger.warning('Docker is not installed')
        return 'not installed'
    except TimeoutError:
        logger.warning('Docker info timed out')
        return 'failed'
    except Exception:
        logger.exception('Failed to check if docker is running')
        report_service_error()
        return 'failed'
    else:
        logger.warning('Docker process returned non-zero exit code')
        return 'not running'


async def _get_envoy_status() -> str:
    cached = _status_cache.get('envoy')
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    result = await _get_envoy_status_uncached()
    _status_cache['envoy'] = (time.time(), result)
    return result


async def _get_envoy_status_uncached() -> str:
    try:
        returncode, output = await _run_docker_command(
            'docker',
            'inspect',
            ENVOY_IMAGE_NAME,
        )
        if returncode == 0:
            if ENVOY_IMAGE_NAME in output:
                ps_returncode, ps_output = await _run_docker_command('docker', 'ps')
                if ps_returncode == 0:
                    return (
                        'running'
                        if ENVOY_IMAGE_NAME in ps_output
                        else 'not running'
                    )
                logger.warning('Docker ps returned non-zero exit code')
                return 'not running'
            return 'not running'
        else:  # noqa: RET505
            logger.warning('Docker inspect returned non-zero exit code')
            return 'not downloaded'
    except TimeoutError:
        logger.warning('Docker envoy check timed out')
        return 'failed'
    except Exception:
        logger.exception('Failed to check if envoy is running')
        report_service_error()
        return 'failed'


def _hotspot_error_notification(content: str) -> NotificationsAddAction:
    return NotificationsAddAction(
        notification=Notification(
            id='web_ui:hotspot_error',
            icon='󱋆',
            title='Web UI Error',
            content=content,
            display_type=NotificationDisplayType.STICKY,
            importance=Importance.HIGH,
        ),
    )


@store.with_state(
    lambda state: state.wifi.is_hotspot_running if hasattr(state, 'wifi') else False,
)
def _is_hotspot_running(is_running: bool) -> bool:  # noqa: FBT001
    return is_running


async def _wait_for_hotspot_running() -> bool:
    """Poll until the wifi service reports the captive hotspot up (~15s cap)."""
    for _ in range(30):
        if _is_hotspot_running():
            return True
        await asyncio.sleep(0.5)
    return False


def _close_hotspot_qr_on_notification_cleared(
    event: NotificationsClearEvent,
) -> None:
    """Drop the QR page once a pending-input notification is cleared or dismissed."""
    if event.notification.id.startswith('web_ui:pending:'):
        pop_hotspot_qr_render()


@store.with_state(lambda state: state.ip.is_connected)
def _store_reports_connected(is_connected: bool | None) -> bool:  # noqa: FBT001
    return bool(is_connected)


async def initialize(event: WebUIInitializeEvent) -> None:
    """Start the hotspot if there is no network connection."""
    # Same robust signal as the wifi Add-flow: ping-based connectivity OR a
    # default route, so the chooser and the hotspot decision stay consistent.
    is_connected = _store_reports_connected() or await has_gateway()
    logger.info(
        'web-ui - initialize hotspot',
        extra={
            'is_connected': is_connected,
            'description': event.description,
        },
    )
    if not is_connected:
        # Fill the dead wait while the radio switches to AP mode (~seconds).
        store.dispatch(
            OpenRenderAction(
                kind='status',
                title='Hotspot',
                props={
                    'icon': '󰖩',
                    'text': 'Switching to hotspot…',
                    'icon_size': 32,
                    'text_font_size': 16,
                },
            ),
        )
        # The wifi service owns the hotspot; ask it to bring up the captive AP
        # and wait until it reports running.
        store.dispatch(WiFiStartHotspotAction(mode='captive'))
        started = await _wait_for_hotspot_running()
        store.dispatch(StackPopAction())
        if not started:
            store.dispatch(
                InputCancelAction(id=event.description.id),
                _hotspot_error_notification(
                    'Failed to start the hotspot, please check the logs.',
                ),
            )
            return
    # Offline (hotspot) only: a button that shows a WiFi-join QR so the user can
    # connect their phone to the hotspot without typing the password.
    actions = [hotspot_qr_action()] if not is_connected else []
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=f'web_ui:pending:{event.description.id}',
                icon='󱋆' if is_connected else '󰖩',
                title='Web UI',
                content=f'[size=18dp]{event.description.prompt}[/size]',
                display_type=NotificationDisplayType.STICKY,
                is_read=True,
                actions=actions,
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
                expiration_timestamp=time.time(),
                show_dismiss_action=False,
                dismiss_on_close=True,
                on_close_id=register_auto_callback(
                    functools.partial(
                        store.dispatch,
                        InputCancelAction(id=event.description.id),
                    ),
                ),
            ),
        ),
    )


def _register_navigation_bindable_actions() -> None:
    """Expose tile-grid navigation for binding (e.g. to IR remote keys).

    Each factory produces a ``WebUIInputAction``; the reducer turns it into a
    ``WebUIInputEvent`` that the browser converts to a synthetic key press, so
    an IR button drives the same navigation a physical keyboard would.
    """
    for key, label, command in (
        ('web-ui:nav:up', 'Web UI: Up', WebUIInputCommand.UP),
        ('web-ui:nav:down', 'Web UI: Down', WebUIInputCommand.DOWN),
        ('web-ui:nav:left', 'Web UI: Left', WebUIInputCommand.LEFT),
        ('web-ui:nav:right', 'Web UI: Right', WebUIInputCommand.RIGHT),
        ('web-ui:nav:select', 'Web UI: Select', WebUIInputCommand.SELECT),
        ('web-ui:nav:back', 'Web UI: Back', WebUIInputCommand.BACK),
        ('web-ui:nav:home', 'Web UI: Home', WebUIInputCommand.HOME),
    ):
        register_bindable_action(
            key,
            label,
            lambda _ctx, command=command: WebUIInputAction(command=command),
            allow_reregister=True,
        )


async def init_service() -> Subscriptions:  # noqa: C901, PLR0915
    """Initialize the web-ui service."""
    _register_navigation_bindable_actions()
    _ = []
    app = Quart(
        'ubo-app',
        template_folder=(Path(__file__).parent / 'templates').absolute().as_posix(),
        static_folder=(Path(__file__).parent / 'web-app' / 'dist')
        .absolute()
        .as_posix(),
    )
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB
    app.debug = WEB_UI_DEBUG_MODE
    shutdown_event: asyncio.Event = asyncio.Event()

    @store.with_state(lambda state: state.web_ui)
    def state(state: WebUIState) -> str:
        return (
            build_message(state, expected_type=GRPCWebUIState).SerializeToString().hex()
        )

    @app.route('/', methods=['GET', 'POST'])
    async def inputs_form() -> str:
        if request.method == 'POST':
            data: dict[str, str] = dict(await request.form)
            request_files = await request.files

            # Upload files via chunked transfer (same path as gRPC)
            for key, value in request_files.items():
                fs = cast('FileStorage', value)
                file_bytes = fs.stream.read()
                if fs.filename:
                    data[f'{key}_name'] = fs.filename
                if file_bytes:
                    chunk_size = UPLOAD_CHUNK_SIZE
                    upload_id = uuid4().hex
                    total_chunks = (len(file_bytes) + chunk_size - 1) // chunk_size
                    store.dispatch(
                        FileUploadStartAction(
                            upload_id=upload_id,
                            filename=fs.filename or key,
                            total_size=len(file_bytes),
                            total_chunks=total_chunks,
                            chunk_size=chunk_size,
                        ),
                        *[
                            FileUploadChunkAction(
                                upload_id=upload_id,
                                chunk_index=i,
                                data=file_bytes[
                                    i * chunk_size : (i + 1) * chunk_size
                                ],
                            )
                            for i in range(total_chunks)
                        ],
                        FileUploadCompleteAction(upload_id=upload_id),
                    )
                    data[f'{key}_upload_id'] = upload_id

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
                            files={},
                            method=InputMethod.WEB_DASHBOARD,
                        ),
                    ),
                )
            await asyncio.sleep(0.1)
        return await render_template(
            'index.jinja2',
            state=state(),
            re=re,
            GRPC_ENVOY_LISTEN_PORT=GRPC_ENVOY_LISTEN_PORT,
            WEB_UI_LISTEN_PORT=WEB_UI_LISTEN_PORT,
            cache_bust=_cache_bust,
        )

    @app.route('/status')
    async def status() -> Response:
        from ubo_app.utils.file_download import get_pending_downloads

        statuses = await asyncio.gather(
            _get_docker_status(),
            _get_envoy_status(),
        )
        pending_downloads = get_pending_downloads()
        response_data: dict[str, object] = {
            'status': 'ok',
            'docker': statuses[0],
            'envoy': statuses[1],
            'state': state(),
        }
        if pending_downloads:
            response_data['pending_downloads'] = pending_downloads
        return Response(
            json.dumps(response_data),
            content_type='application/json',
        )

    @app.route('/download/<token>')
    async def download_file(token: str) -> Response:
        from ubo_app.utils.file_download import consume_download

        session = consume_download(token)
        if not session:
            return Response('Download not found or expired', status=404)

        file_path = Path(session.file_path)
        if not file_path.exists():
            return Response('File not found', status=404)

        response = await send_file(
            file_path,
            as_attachment=True,
            attachment_filename=session.filename,
        )

        if session.is_temp:

            async def _cleanup_temp() -> None:
                # Wait briefly for download to complete before cleanup
                await asyncio.sleep(60)
                file_path.unlink(missing_ok=True)
                if file_path.parent.name.startswith('ubo_download_'):
                    import contextlib

                    with contextlib.suppress(OSError):
                        file_path.parent.rmdir()

            create_task(_cleanup_temp())

        return response

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
            store.dispatch(DockerImageRunAction(image='envoy_grpc'))
        elif action == 'remove envoy':
            store.dispatch(DockerImageStopAction(image='envoy_grpc'))
            await asyncio.sleep(2)
            store.dispatch(DockerImageRemoveContainerAction(image='envoy_grpc'))
            await asyncio.sleep(2)
            store.dispatch(DockerImageRemoveAction(image='envoy_grpc'))
        return Response(
            json.dumps({'status': 'ok'}),
            content_type='application/json',
        )

    if WEB_UI_DEBUG_MODE:

        @app.errorhandler(Exception)
        async def handle_error(_: Exception) -> str:
            import traceback

            return f'<pre>{traceback.format_exc()}</pre>'

        _.append(handle_error)

    store.subscribe_event(WebUIInitializeEvent, initialize)
    store.subscribe_event(
        NotificationsClearEvent,
        _close_hotspot_qr_on_notification_cleared,
    )

    start_event = asyncio.Event()

    async def wait_for_shutdown() -> None:
        await shutdown_event.wait()

    app.before_serving(start_event.set)

    create_task(
        app.run_task(
            host=WEB_UI_LISTEN_ADDRESS,
            port=WEB_UI_LISTEN_PORT,
            debug=WEB_UI_DEBUG_MODE,
            shutdown_trigger=wait_for_shutdown,
        ),
    )

    await start_event.wait()

    async def cleanup() -> None:
        shutdown_event.set()

    return [cleanup]
