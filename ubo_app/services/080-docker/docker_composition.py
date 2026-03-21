"""Docker composition management."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import replace

from calculate_progress import (
    LayerProgressTracker,
    ServiceTrackers,
    calculate_composition_progress,
)
from docker_images import IMAGES, PREDEFINED_IMAGE_IDS

from ubo_app.colors import DANGER_COLOR
from ubo_app.constants import CONFIG_PATH
from ubo_app.logger import logger
from ubo_app.store.core.types import DeregisterRegularAppAction
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageFetchCompositionEvent,
    DockerImageReleaseCompositionEvent,
    DockerImageRemoveCompositionEvent,
    DockerImageRunCompositionEvent,
    DockerImageSetStatusAction,
    DockerImageStopCompositionEvent,
    DockerItemStatus,
)
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils import IS_RPI, secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.log_process import log_async_process
from ubo_app.utils.server import send_command

COMPOSITIONS_PATH = CONFIG_PATH / 'docker_compositions'
DOCKER_COMPOSITION_FETCH_PROGRESS_NOTIFICATION_ID = (
    'docker:composition_fetch_progress:{}'
)


def _create_composition_fetch_notification(
    composition_id: str,
    label: str,
    content: str,
    progress: float | None = 0,
) -> Notification:
    """Create a fetch progress notification for a composition."""
    return Notification(
        id=DOCKER_COMPOSITION_FETCH_PROGRESS_NOTIFICATION_ID.format(composition_id),
        title=label,
        content=content,
        display_type=NotificationDisplayType.BACKGROUND,
        icon='󰡨',
        show_dismiss_action=False,
        progress=progress,
    )


async def stop_composition(event: DockerImageStopCompositionEvent) -> None:
    """Stop the composition."""
    id = event.image

    store.dispatch(
        DockerImageSetStatusAction(image=id, status=DockerItemStatus.PROCESSING),
    )
    stop_process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'stop',
        cwd=COMPOSITIONS_PATH / id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await stop_process.wait()
    store.dispatch(
        await log_async_process(
            stop_process,
            title='Docker Composition Error',
            message='Failed to stop composition.',
        ),
    )
    await check_composition(id=id)


async def run_composition(event: DockerImageRunCompositionEvent) -> None:
    """Run the composition."""
    id = event.image

    store.dispatch(
        DockerImageSetStatusAction(image=id, status=DockerItemStatus.PROCESSING),
    )
    run_process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'up',
        '-d',
        cwd=COMPOSITIONS_PATH / id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await run_process.wait()
    store.dispatch(
        await log_async_process(
            run_process,
            title='Docker Composition Error',
            message='Failed to run composition.',
        ),
    )
    await check_composition(id=id)


async def remove_composition(event: DockerImageRemoveCompositionEvent) -> None:
    """Remove the composition."""
    id = event.image
    logger.info('Removing composition', extra={'composition_id': id})

    store.dispatch(
        DockerImageSetStatusAction(image=id, status=DockerItemStatus.PROCESSING),
    )

    # Tear down containers and volumes before removing the directory.
    # The `-v` flag removes named volumes (e.g. postgres data) so that
    # a fresh install doesn't reuse stale credentials/data.
    composition_path = COMPOSITIONS_PATH / id
    if composition_path.exists():
        try:
            down_process = await asyncio.subprocess.create_subprocess_exec(
                'docker',
                'compose',
                'down',
                '-v',
                cwd=composition_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await down_process.wait()
            store.dispatch(
                await log_async_process(
                    down_process,
                    title='Docker Composition Error',
                    message='Failed to tear down composition.',
                ),
            )
        except OSError:
            logger.exception(
                'Failed to run docker compose down -v',
                extra={'composition_id': id},
            )

    # Remove composition directory
    # On Pi: use system manager with elevated privileges
    # (Docker creates root-owned directories)
    # On Mac/dev: use shutil.rmtree (no elevated privileges needed)
    try:
        if IS_RPI:
            await send_command(
                'docker',
                'composition_delete',
                str(composition_path),
            )
        # Development environment - use shutil directly
        elif composition_path.exists():
            shutil.rmtree(composition_path)
    except Exception:
        logger.exception(
            'Failed to remove composition directory',
            extra={'composition_id': id},
        )

    # Clear stored secrets for this composition
    if id in IMAGES:
        for key in IMAGES[id].secret_keys:
            secrets.clear_secret(key)

    # For predefined compositions (immich, n8n, etc.), keep them in the menu
    # as re-installable. Only fully remove dynamically-loaded compositions.
    if id in PREDEFINED_IMAGE_IDS:
        store.dispatch(
            DockerImageSetStatusAction(
                image=id,
                status=DockerItemStatus.NOT_AVAILABLE,
            ),
        )
        logger.info(
            'Reset predefined composition to NOT_AVAILABLE',
            extra={'composition_id': id},
        )
    elif id in IMAGES:
        del IMAGES[id]
        logger.info('Removed composition from IMAGES', extra={'composition_id': id})

        # Remove from menu
        store.dispatch(
            DeregisterRegularAppAction(
                key=id,
            ),
        )


async def get_composition_label(composition_id: str) -> str:
    """Get the label for a composition from metadata."""
    try:
        # Try to read from metadata.json
        metadata_path = COMPOSITIONS_PATH / composition_id / 'metadata.json'
        if metadata_path.exists():
            with metadata_path.open() as f:
                metadata = json.load(f)
                return metadata.get('label', composition_id)
    except Exception:
        logger.exception(
            'Failed to read metadata.json',
            extra={'composition_id': composition_id},
        )

    # Fallback to composition_id
    return composition_id.replace('_', ' ').title()


async def _get_composition_image_count(composition_id: str) -> int:
    """Get the number of images in a composition."""
    logger.debug(
        'Starting composition image count',
        extra={
            'composition_id': composition_id,
            'path': COMPOSITIONS_PATH / composition_id,
        },
    )
    try:
        config_process = await asyncio.subprocess.create_subprocess_exec(
            'docker',
            'compose',
            'config',
            '--images',
            cwd=COMPOSITIONS_PATH / composition_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info('Process created, waiting for output',
                    extra={'composition_id': composition_id})
        stdout, stderr = await config_process.communicate()
        logger.info(
            'Got process output',
            extra={
                'composition_id': composition_id,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'returncode': config_process.returncode,
            },
        )
        image_list = [img for img in stdout.decode().strip().split('\n') if img]
        logger.info(
            'Got composition image list',
            extra={'composition_id': composition_id, 'image_list': image_list},
        )
        return len(image_list)
    except (OSError, ValueError) as e:
        logger.exception(
            'Failed to get composition image count',
            extra={'composition_id': composition_id, 'error': str(e)},
        )
        return 0

def _process_layer_line(
    layer_match: re.Match[str],
    current_service: str | None,
    service_trackers: ServiceTrackers,
) -> None:
    """Process a layer progress line from docker compose output.

    Args:
        layer_match: Regex match object for layer line
        current_service: Name of the current service being processed
        service_trackers: Dict mapping service names to their trackers

    """
    if not current_service:
        return

    layer_id = layer_match.group(1)
    rest_of_line = layer_match.group(2)

    # Check if there's bracketed progress info
    bracket_match = re.search(r'\[(.+?)\]\s*(.+)$', rest_of_line)
    if bracket_match:
        # Format: "status [progress bar] size_info"  # noqa: ERA001
        # Extract status (everything before bracket)
        status = rest_of_line[:rest_of_line.index('[')].strip()
        progress = bracket_match.group(2).strip()  # Size info after bracket
    else:
        # No brackets, entire rest is status
        status = rest_of_line.strip()
        progress = ''

    if current_service in service_trackers:
        service_trackers[current_service].update_layer(
            layer_id,
            status,
            progress,
        )
        logger.debug(
            'Layer update',
            extra={
                'service': current_service,
                'layer': layer_id,
                'status': status,
                'progress': progress,
            },
        )


def _process_service_line(
    service_match: re.Match[str],
    service_trackers: ServiceTrackers,
    completed_services: set[str],
) -> str | None:
    """Process a service-level status line from docker compose output.

    Args:
        service_match: Regex match object for service line
        service_trackers: Dict mapping service names to their trackers
        completed_services: Set to track which services have completed

    Returns:
        The service name if it's currently pulling, None otherwise

    """
    service_name = service_match.group(1)
    status = service_match.group(2)

    # Track which service we're currently processing
    if 'Pulling' in status:
        if service_name not in service_trackers:
            service_trackers[service_name] = LayerProgressTracker(service_name)
        logger.info(
            'Service pulling started',
            extra={'service_name': service_name},
        )
        return service_name

    # Mark service as complete
    if 'Pulled' in status or 'Already exists' in status:
        completed_services.add(service_name)
        # Mark all layers of this service as complete
        if service_name in service_trackers:
            service_trackers[service_name].mark_all_complete()
        logger.info('Service completed', extra={
            'service_name': service_name,
            'status': status,
            'total_completed': len(completed_services),
        })

    return None


async def _stream_pull_output(
    process: asyncio.subprocess.Process,
    service_trackers: ServiceTrackers,
    completed_services: set[str],
) -> None:
    """Stream docker compose pull output and track service progress.

    Args:
        process: The subprocess running docker compose pull
        service_trackers: Dict mapping service names to their LayerProgressTracker
        completed_services: Set to track which services have completed

    """
    if not process.stdout:
        return

    current_service = None

    while True:
        line_bytes = await process.stdout.readline()
        if not line_bytes:
            break

        line = line_bytes.decode('utf-8', errors='ignore').strip()
        if not line:
            continue

        logger.debug('Got line', extra={'line': line})

        # Docker Compose outputs two types of lines:
        # 1. Service-level: "service-name Pulling" or "service-name Pulled"
        # 2. Layer-level: "hash-id status [progress]" (12-char hex hash)

        # Check if this is a layer hash line (12-character hex at start)
        # Format examples:
        # "22f7f53393bf Already exists"
        # "9a80f9a05524 Download complete"
        # "6f22bf4a69c6 Downloading [==> ] 1.5MB/10MB" # noqa: ERA001
        layer_match = re.match(r'^([a-f0-9]{12})\s+(.+)$', line)
        if layer_match:
            _process_layer_line(layer_match, current_service, service_trackers)
        else:
            # Service-level status line
            service_match = re.match(r'^([\w-]+)\s+(.+)', line)
            if service_match:
                new_service = _process_service_line(
                    service_match,
                    service_trackers,
                    completed_services,
                )
                if new_service:
                    current_service = new_service


async def _handle_pull_success(
    base_notification: Notification,
) -> None:
    """Handle successful composition pull."""
    store.dispatch(
        NotificationsAddAction(
            notification=replace(
                base_notification,
                content='All images pulled!',
                progress=1.0,
                display_type=NotificationDisplayType.FLASH,
                show_dismiss_action=True,
                dismiss_on_close=True,
                chime=Chime.DONE,
            ),
        ),
    )


async def _handle_pull_error(
    base_notification: Notification,
    process: asyncio.subprocess.Process | None = None,
) -> None:
    """Handle composition pull error."""
    notification_action = NotificationsAddAction(
        notification=replace(
            base_notification,
            content='Pull failed',
            color=DANGER_COLOR,
            display_type=NotificationDisplayType.FLASH,
            dismiss_on_close=True,
            chime=Chime.FAILURE,
            show_dismiss_action=True,
            progress=None,
        ),
    )

    if process:
        store.dispatch(
            notification_action,
            await log_async_process(
                process,
                title='Docker Composition Error',
                message='Failed to pull composition images.',
            ),
        )
    else:
        store.dispatch(notification_action)


async def pull_composition(event: DockerImageFetchCompositionEvent) -> None:
    """Pull the composition images with progress tracking."""
    from docker_app import prepare_app

    id = event.image
    container = IMAGES[id]

    logger.info('About to call prepare_app', extra={'image': id})
    # Prepare the composition (download files, generate credentials, update metadata)
    if not await prepare_app(container):
        logger.error('prepare_app returned False, exiting', extra={'image': id})
        return

    composition_label = await get_composition_label(id)
    total_images = await _get_composition_image_count(id)

    # Create base notification
    base_notification = _create_composition_fetch_notification(
        id,
        composition_label,
        f'Pulling {total_images} image{"s" if total_images != 1 else ""}...',
    )

    # Dispatch initial status and notification
    store.dispatch(
        DockerImageSetStatusAction(image=id, status=DockerItemStatus.FETCHING),
        NotificationsAddAction(notification=base_notification),
    )

    # Track service progress
    service_trackers: ServiceTrackers = {}
    completed_services: set[str] = set()
    update_interval = 1.0

    try:
        run_process = await asyncio.subprocess.create_subprocess_exec(
            'docker',
            'compose',
            'pull',
            cwd=COMPOSITIONS_PATH / id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Stream output and track progress in background
        stream_task = asyncio.create_task(
            _stream_pull_output(run_process, service_trackers, completed_services),
        )

        # Update progress periodically while streaming
        while not stream_task.done():
            # Wait up to update_interval or until streaming completes
            done, _ = await asyncio.wait(
                [stream_task],
                timeout=update_interval,
            )

            # Update progress if task is still running
            if not done:
                progress = calculate_composition_progress(
                    service_trackers,
                    completed_services,
                    total_images,
                )
                # Count completed services
                completed = len(completed_services)
                store.dispatch(
                    NotificationsAddAction(
                        notification=replace(
                            base_notification,
                            content=(
                                f'Pulling images... ({completed}/'
                                f'{total_images if total_images > 0 else "?"}'
                            ),
                            progress=progress,
                        ),
                    ),
                )

        # Ensure streaming task completes
        await stream_task
        await run_process.wait()

        if run_process.returncode != 0:
            await _handle_pull_error(base_notification, run_process)
        else:
            await _handle_pull_success(base_notification)

    except (OSError, ValueError) as e:
        logger.exception(
            'Failed to pull composition',
            extra={'composition_id': id, 'error': str(e)},
        )
        await _handle_pull_error(base_notification)

    finally:
        # Clean up progress trackers to prevent memory leak
        # Each tracker contains layer dictionaries that can grow large
        service_trackers.clear()
        completed_services.clear()
        logger.debug(
            'Cleaned up progress trackers',
            extra={'composition_id': id},
        )
        await check_composition(id=id)


async def _release_composition(id: str) -> None:
    store.dispatch(
        DockerImageSetStatusAction(image=id, status=DockerItemStatus.PROCESSING),
    )
    check_process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'down',
        cwd=COMPOSITIONS_PATH / id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await check_process.wait()
    store.dispatch(
        await log_async_process(
            check_process,
            title='Docker Composition Error',
            message='Failed to release resources.',
        ),
    )
    await check_composition(id=id)


def release_composition(event: DockerImageReleaseCompositionEvent) -> None:
    """Release resources of composition."""
    id = event.image
    create_task(_release_composition(id))


async def check_composition(*, id: str) -> None:
    """Check the status of the composition."""
    # Check if composition directory exists
    composition_path = COMPOSITIONS_PATH / id
    if not composition_path.exists():
        # Directory doesn't exist - set status to NOT_AVAILABLE
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.NOT_AVAILABLE),
        )
        return

    # Check if containers are running
    ps_running = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'ps',
        '--quiet',
        cwd=composition_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Check all containers (including stopped)
    ps_all = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'ps',
        '-a',
        '--quiet',
        cwd=composition_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Get required images from compose file
    config = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'config',
        '--images',
        cwd=composition_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    await asyncio.gather(
        ps_running.wait(),
        ps_all.wait(),
        config.wait(),
        return_exceptions=True,
    )

    store.dispatch(
        *await asyncio.gather(
            log_async_process(
                ps_running,
                title='Docker Composition Error',
                message='Failed to check running containers.',
            ),
            log_async_process(
                ps_all,
                title='Docker Composition Error',
                message='Failed to check containers.',
            ),
            log_async_process(
                config,
                title='Docker Composition Error',
                message='Failed to check composition config.',
            ),
        ),
    )

    # Check if containers are running
    ps_running_output = await ps_running.stdout.read() if ps_running.stdout else b''
    if ps_running_output:
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.RUNNING),
        )
        return

    # Check if containers exist (even if stopped)
    ps_all_output = await ps_all.stdout.read() if ps_all.stdout else b''
    if ps_all_output:
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.CREATED),
        )
        return

    # Check if images are pulled
    config_output = await config.stdout.read() if config.stdout else b''
    if config_output:
        image_names = config_output.decode().strip().split('\n')
        all_exist = True
        for image_name in image_names:
            if not image_name:
                continue
            inspect = await asyncio.subprocess.create_subprocess_exec(
                'docker',
                'image',
                'inspect',
                image_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await inspect.wait()
            if inspect.returncode != 0:
                all_exist = False
                break

        status = DockerItemStatus.AVAILABLE if \
                all_exist else DockerItemStatus.NOT_AVAILABLE
        store.dispatch(DockerImageSetStatusAction(image=id, status=status))
    else:
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.NOT_AVAILABLE),
        )
