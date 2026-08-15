"""Port monitoring for Docker apps — probes until the app serves HTTP."""

from __future__ import annotations

import asyncio

import aiohttp

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageSetStatusAction,
    DockerItemStatus,
)

_active_monitors: set[str] = set()


def _first_host_port(
    ports: dict[str, int | list[int] | tuple[str, int] | None],
) -> int | None:
    """Extract the first usable host port from a ContainerEntry's ports dict."""
    for value in ports.values():
        if isinstance(value, int):
            return value
        if isinstance(value, list) and value and isinstance(value[0], int):
            return value[0]
        if isinstance(value, tuple) and len(value) > 1 and isinstance(value[1], int):
            return value[1]
    return None


async def _probe_http(port: int) -> bool:
    """Send an HTTP GET to localhost:port and return True on any HTTP response.

    Any status code (200, 401, 403, 404, 500, ...) means the server is up.
    Only connection-level failures (refused, reset, timeout) count as "not
    ready yet."
    """
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f'http://127.0.0.1:{port}/',
                timeout=aiohttp.ClientTimeout(total=3),
            ) as response,
        ):
            _ = response.status
    except (OSError, aiohttp.ClientError, TimeoutError):
        return False
    else:
        return True


async def monitor_app_port(
    image_id: str,
    port: int,
    *,
    max_wait: float = 120,
    interval: float = 3,
) -> None:
    """Probe ``port`` until the HTTP server responds, then set RUNNING.

    If ``max_wait`` seconds elapse without a successful probe the status is
    left alone. It stays at STARTING, which is the truth: the container is up
    but nothing is answering on its port yet.
    """
    if image_id in _active_monitors:
        return
    _active_monitors.add(image_id)

    try:
        elapsed = 0.0
        while elapsed < max_wait:
            await asyncio.sleep(interval)
            elapsed += interval

            if await _probe_http(port):
                logger.info(
                    'Port is ready',
                    extra={'image': image_id, 'port': port},
                )
                store.dispatch(
                    DockerImageSetStatusAction(
                        image=image_id,
                        status=DockerItemStatus.RUNNING,
                    ),
                )
                return

        # Deliberately no dispatch. Declaring RUNNING on a probe that never
        # answered is how a crash-looping app came to report itself healthy:
        # with `restart_policy: always` it never serves the port, so it hit
        # this branch every time and landed on RUNNING.
        logger.warning(
            'Port probe timed out, leaving status unchanged',
            extra={'image': image_id, 'port': port, 'max_wait': max_wait},
        )
    finally:
        _active_monitors.discard(image_id)
