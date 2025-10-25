"""Docker composition management."""

from __future__ import annotations

import asyncio
import shutil

from ubo_app.constants import CONFIG_PATH
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
from ubo_app.utils.async_ import create_task
from ubo_app.utils.log_process import log_async_process

COMPOSITIONS_PATH = CONFIG_PATH / 'docker_compositions'


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


async def pull_composition(event: DockerImageFetchCompositionEvent) -> None:
    """Pull the composition images."""
    id = event.image

    store.dispatch(
        DockerImageSetStatusAction(image=id, status=DockerItemStatus.FETCHING),
    )
    run_process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'pull',
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
