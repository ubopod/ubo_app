"""Utility functions for downloading files."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiofiles
import aiohttp

from ubo_app.logger import logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


async def download_file(
    *,
    url: str,
    path: Path,
    progress_step: float | None = 0.05,
) -> AsyncGenerator[tuple[int, int | None], None]:
    """Download a file from a URL and save it to a local path.

    Args:
        url: HTTP URL to download from.
        path: Destination path on disk.
        progress_step: Fractional gate on yield frequency (default 0.05 =
            5 %). The generator yields only when the current download
            progress (``downloaded_bytes / total_size``) crosses into a
            new step, plus the final chunk. Keeps downstream consumers
            (e.g. a status-bar progress wheel) from being flooded with
            sub-pixel updates. Pass ``None`` to yield on every chunk.
            Falls back to every-chunk yields when ``total_size`` is
            unknown (no ``Content-Length`` header).

    """
    downloaded_bytes = 0
    async with (
        aiohttp.ClientSession() as session,
        session.get(url, raise_for_status=True) as response,
    ):
        total_size_header = response.headers.get('Content-Length')
        if total_size_header:
            try:
                total_size = int(total_size_header)
                if total_size <= 0:
                    logger.warning(
                        'Piper: Invalid Content-Length header',
                        extra={'header': total_size_header},
                    )
                    total_size = None
            except ValueError:
                logger.warning(
                    'Piper: Invalid Content-Length header',
                    extra={'header': total_size_header},
                )
                total_size = None
        else:
            logger.warning('Piper: No Content-Length header')
            total_size = None

        last_step = -1
        async with aiofiles.open(path, mode='wb') as f:
            async for chunk in response.content.iter_chunked(1024 * 16):
                await f.write(chunk)
                downloaded_bytes += len(chunk)
                if progress_step is None or total_size is None:
                    # No gating: emit every chunk (caller opted out, or
                    # the total size is unknown so we can't step-gate).
                    yield (downloaded_bytes, total_size)
                    continue
                step = int((downloaded_bytes / total_size) / progress_step)
                if step != last_step or downloaded_bytes >= total_size:
                    last_step = step
                    yield (downloaded_bytes, total_size)
