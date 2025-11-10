"""Docker composition management."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import replace

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
from ubo_app.utils.async_ import create_task
from ubo_app.utils.log_process import log_async_process

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
        stdout, _ = await config_process.communicate()
        image_list = [img for img in stdout.decode().strip().split('\n') if img]
        return len(image_list)
    except (OSError, ValueError) as e:
        logger.debug(
            'Failed to get composition image count',
            extra={'composition_id': composition_id, 'error': str(e)},
        )
        return 0


async def _stream_pull_output(
    process: asyncio.subprocess.Process,
    pulled_images: set[str],
) -> None:
    """Stream docker compose pull output and track completed images.

    Args:
        process: The subprocess running docker compose pull
        pulled_images: Set to track which images have been pulled

    """
    if not process.stdout:
        return

    while True:
        line_bytes = await process.stdout.readline()
        if not line_bytes:
            break

        line = line_bytes.decode('utf-8', errors='ignore').strip()

        # Docker Compose outputs lines like:
        # "service-name Pulled" or "service-name Already exists"
        # We only care about completion status
        if line and not line.startswith(' '):
            service_match = re.match(r'^([\w-]+)\s+(.+)', line)
            if service_match:
                service_name = service_match.group(1)
                status = service_match.group(2)

                # Mark image as pulled when complete
                if 'Pulled' in status or 'Already exists' in status:
                    pulled_images.add(service_name)


def _calculate_composition_progress(
    pulled_images: set[str],
    total_count: int,
) -> float:
    """Calculate overall progress for composition pull.

    Args:
        pulled_images: Set of completed image names
        total_count: Total number of images expected

    Returns:
        Overall progress as float between 0.0 and 1.0

    """
    if total_count == 0:
        # Unknown total, show indeterminate progress
        return 0.5

    # Calculate progress based on completed images
    return min(len(pulled_images) / total_count, 0.99)


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
    id = event.image
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

    # Track which images have been pulled
    pulled_images: set[str] = set()
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
            _stream_pull_output(run_process, pulled_images),
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
                progress = _calculate_composition_progress(
                    pulled_images,
                    total_images,
                )
                # Count completed images
                completed = len(pulled_images)
                store.dispatch(
                    NotificationsAddAction(
                        notification=replace(
                            base_notification,
                            content=(
                                f'Pulling images... ({completed}/'
                                f'{total_images if total_images > 0 else "?"})'
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


async def remove_composition(event: DockerImageRemoveCompositionEvent) -> None:
    """Delete the composition."""
    id = event.image

    # Stop containers and remove images
    store.dispatch(
        DockerImageSetStatusAction(image=id, status=DockerItemStatus.PROCESSING),
    )
    down_process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'down',
        '--rmi',
        'all',
        '--volumes',
        cwd=COMPOSITIONS_PATH / id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await down_process.wait()
    store.dispatch(
        await log_async_process(
            down_process,
            title='Docker Composition Error',
            message='Failed to remove composition.',
        ),
    )

    # Remove composition directory
    shutil.rmtree(COMPOSITIONS_PATH / id)

    # Only deregister manual compositions, not presets
    # Presets should remain in the app list so users can reinstall
    if not id.startswith('preset_'):
        store.dispatch(DeregisterRegularAppAction(key=id))
    else:
        # Reset preset status to NOT_AVAILABLE
        await check_composition(id=id)
