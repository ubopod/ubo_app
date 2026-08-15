"""Per-app log tail, rendered as a generic ``text_viewer`` render view.

The Docker menu used to tell the user "We have an error, please check the logs"
without offering anywhere to check them. This is that place.

Deliberately a *polled snapshot*, not a followed stream. The text lands in
``RenderStackItem.props``, i.e. in Redux state, and the top view is re-packed
and pushed to every connected client — including the ESP32, which decodes it
onto a ~50 KB heap and copies the string again into the LVGL label. The budget
that survives is small, so this keeps the same 2 KiB ceiling the file viewer
settled on (``090-file-system/file_application.py``) and reads only the last
handful of lines.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import docker
from apps import IMAGES
from apps._registry import COMPOSITIONS_PATH
from docker_container import find_container
from log_format import LOG_TAIL_LINES, PLACEHOLDER, format_logs

from ubo_app.logger import logger
from ubo_app.store.core.types import RenderStackItem, UpdateRenderPropsAction
from ubo_app.store.main import store
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from ubo_app.store.main import RootState

LOG_REFRESH_INTERVAL = 2

_STREAM_PREFIX = 'docker:logs:'


def stream_id(image_id: str) -> str:
    """Identify one app's logs page, so updates find the open one."""
    return f'{_STREAM_PREFIX}{image_id}'


def _read_container_logs(image_id: str) -> str:
    """Read one container's tail. Blocking — callers hand this to a thread."""
    docker_client = docker.from_env()
    try:
        container = find_container(docker_client, image_path=IMAGES[image_id].path)
        if container is None:
            return ''
        return container.logs(tail=LOG_TAIL_LINES).decode('utf-8', errors='replace')
    finally:
        docker_client.close()


async def _read_composition_logs(image_id: str) -> str:
    """Read a stack's tail.

    The per-service prefix is kept: on a composition, *which* service is
    complaining is most of the answer.
    """
    process = await asyncio.subprocess.create_subprocess_exec(
        'docker',
        'compose',
        'logs',
        '--no-color',
        '--tail',
        str(LOG_TAIL_LINES),
        cwd=COMPOSITIONS_PATH / image_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    return stdout.decode('utf-8', errors='replace')


async def _read_logs(image_id: str) -> str:
    """Read the current tail for an app, whichever kind it is."""
    entry = IMAGES.get(image_id)
    if entry is None:
        return ''
    try:
        if entry.is_composition:
            return await _read_composition_logs(image_id)
        return await asyncio.to_thread(_read_container_logs, image_id)
    except Exception:
        # A log read failing must not take the page down with it — the app is
        # very likely mid-crash, which is exactly when the user is looking.
        logger.exception('Failed to read logs', extra={'image': image_id})
        return ''


# Which app's logs are on screen, or None. The tail loop re-reads this every
# pass and exits when it changes, so navigating away — or straight to another
# app's logs — retires the previous loop without needing to hold a handle.
_open_image: list[str | None] = [None]


async def _tail_loop(image_id: str) -> None:
    """Refresh the open logs page until it stops being the open logs page."""
    previous: str | None = None
    while _open_image[0] == image_id:
        text = format_logs(await _read_logs(image_id)) or PLACEHOLDER
        # Re-dispatching identical text would re-pack the whole view for every
        # client, twice a second, to say nothing new.
        if text != previous and _open_image[0] == image_id:
            previous = text
            store.dispatch(
                UpdateRenderPropsAction(
                    stream_id=stream_id(image_id),
                    props={'text': text},
                ),
            )
        await asyncio.sleep(LOG_REFRESH_INTERVAL)


def open_logs_image(state: RootState) -> str | None:
    """Select the app whose logs page is on top of the stack, if any.

    Only the *top* counts. A logs page buried under a notification is not on
    screen, and polling docker to refresh something nobody can see costs a
    subprocess every couple of seconds for nothing.
    """
    if not state.main.stack:
        return None
    item = state.main.stack[-1]
    if not isinstance(item, RenderStackItem) or not item.stream_id.startswith(
        _STREAM_PREFIX,
    ):
        return None
    return item.stream_id.removeprefix(_STREAM_PREFIX)


def sync_log_tail(image_id: str | None) -> None:
    """Start tailing the newly-opened logs page, and stop tailing the old one."""
    if _open_image[0] == image_id:
        return
    _open_image[0] = image_id
    if image_id is not None:
        create_task(_tail_loop(image_id))


def stop_log_tail() -> None:
    """Retire any running tail loop, for service teardown.

    The autorun's own unsubscribe only stops *future* syncs; a loop already
    sleeping between passes would otherwise outlive the service and go on
    dispatching into reducers that no longer exist.
    """
    _open_image[0] = None
