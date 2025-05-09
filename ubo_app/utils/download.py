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
) -> AsyncGenerator[tuple[int, int | None], None]:
    """Download a file from a URL and save it to a local path."""
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

        async with aiofiles.open(path, mode='wb') as f:
            async for chunk in response.content.iter_chunked(1024 * 16):
                await f.write(chunk)
                downloaded_bytes += len(chunk)
                yield (downloaded_bytes, total_size)
