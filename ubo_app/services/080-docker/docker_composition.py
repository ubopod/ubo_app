"""Docker composition management."""

from __future__ import annotations

import asyncio
import shutil
import subprocess

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


def stop_composition(event: DockerImageStopCompositionEvent) -> None:
    """Stop the composition."""
    id = event.image

    async def act() -> None:
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.PROCESSING),
        )
        stop_process = await asyncio.subprocess.create_subprocess_exec(
            'docker',
            'compose',
            'stop',
            cwd=COMPOSITIONS_PATH / id,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        await stop_process.wait()
        await log_async_process(
            stop_process,
            title='Docker Composition Error',
            message='Failed to stop composition.',
        )
        await check_composition(id=id)

    create_task(act())


def run_composition(event: DockerImageRunCompositionEvent) -> None:
    """Run the composition."""
    id = event.image

    async def act() -> None:
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.PROCESSING),
        )
        run_process = await asyncio.subprocess.create_subprocess_exec(
            'docker',
            'compose',
            'up',
            '-d',
            cwd=COMPOSITIONS_PATH / id,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        await run_process.wait()
        await log_async_process(
            run_process,
            title='Docker Composition Error',
            message='Failed to run composition.',
        )
        await check_composition(id=id)

    create_task(act())


def pull_composition(event: DockerImageFetchCompositionEvent) -> None:
    """Pull the composition images."""
    id = event.image

    async def act() -> None:
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.FETCHING),
        )
        run_process = await asyncio.subprocess.create_subprocess_exec(
            'docker',
            'compose',
            'pull',
            cwd=COMPOSITIONS_PATH / id,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        await run_process.wait()
        await log_async_process(
            run_process,
            title='Docker Composition Error',
            message='Failed to run composition.',
        )
        await check_composition(id=id)

    create_task(act())


async def _release_composition(id: str) -> None:
    store.dispatch(
        DockerImageSetStatusAction(image=id, status=DockerItemStatus.PROCESSING),
    )
    check_process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'down',
        cwd=COMPOSITIONS_PATH / id,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    await check_process.wait()
    await log_async_process(
        check_process,
        title='Docker Composition Error',
        message='Failed to release resources.',
    )
    await check_composition(id=id)


def release_composition(event: DockerImageReleaseCompositionEvent) -> None:
    """Release resources of composition."""
    id = event.image
    create_task(_release_composition(id))


async def check_composition(*, id: str) -> None:
    """Check the status of the composition."""
    ps_process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'ps',
        '--quiet',
        cwd=COMPOSITIONS_PATH / id,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    images_process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'images',
        '--quiet',
        cwd=COMPOSITIONS_PATH / id,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    await asyncio.gather(
        ps_process.wait(),
        images_process.wait(),
        return_exceptions=True,
    )
    await asyncio.gather(
        log_async_process(
            ps_process,
            title='Docker Composition Error',
            message='Failed to check composition status.',
        ),
        log_async_process(
            images_process,
            title='Docker Composition Error',
            message='Failed to check composition images.',
        ),
    )
    if ps_process.stdout and await ps_process.stdout.read():
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.RUNNING),
        )
    elif images_process.stdout and await images_process.stdout.read():
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.CREATED),
        )
    else:
        store.dispatch(
            DockerImageSetStatusAction(image=id, status=DockerItemStatus.AVAILABLE),
        )


def remove_composition(event: DockerImageRemoveCompositionEvent) -> None:
    """Delete the composition."""
    id = event.image

    async def act() -> None:
        await _release_composition(id=id)
        shutil.rmtree(COMPOSITIONS_PATH / id)
        store.dispatch(DeregisterRegularAppAction(key=id))

    create_task(act())
