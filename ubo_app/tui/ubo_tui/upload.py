"""Chunked file upload helper for the TUI."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from pathlib import Path

    from ubo_tui.client import TUIClient

logger = logging.getLogger(__name__)

# Match the WebUI client (web-app/src/inputs.tsx CHUNK_SIZE).
CHUNK_SIZE = 512 * 1024  # 512 KB
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0


ProgressCallback = Callable[[int, int], Awaitable[None] | None]


async def upload_file(
    client: TUIClient,
    upload_id: str,
    path: Path,
    *,
    target_directory: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Send ``path`` to the device in chunked FileUpload* actions.

    Mirrors the protocol from ``web-app/src/inputs.tsx::chunkedUpload``:

    1. Dispatch ``FileUploadStartAction`` with metadata.
    2. Dispatch ``FileUploadChunkAction`` once per 512KB slice (sequential
       in the TUI, with retries).
    3. Dispatch ``FileUploadCompleteAction``.
    """
    total_size = path.stat().st_size
    total_chunks = max(1, (total_size + CHUNK_SIZE - 1) // CHUNK_SIZE)
    filename = path.name

    logger.info(
        "upload_file: id=%s path=%s size=%d chunks=%d",
        upload_id,
        path,
        total_size,
        total_chunks,
    )

    client.upload_file_start(
        upload_id=upload_id,
        filename=filename,
        total_size=total_size,
        total_chunks=total_chunks,
        chunk_size=CHUNK_SIZE,
        target_directory=target_directory,
    )

    sent = 0
    with path.open("rb") as fh:
        for index in range(total_chunks):
            data = fh.read(CHUNK_SIZE)
            if not data:
                break
            await _dispatch_chunk_with_retries(client, upload_id, index, data)
            sent += 1
            if on_progress is not None:
                result = on_progress(sent, total_chunks)
                if asyncio.iscoroutine(result):
                    await result

    client.upload_file_complete(upload_id=upload_id)
    logger.info("upload_file: id=%s complete", upload_id)


async def _dispatch_chunk_with_retries(
    client: TUIClient,
    upload_id: str,
    chunk_index: int,
    data: bytes,
) -> None:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            client.upload_file_chunk(
                upload_id=upload_id,
                chunk_index=chunk_index,
                data=data,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Chunk %d dispatch failed (attempt %d/%d): %s",
                chunk_index,
                attempt + 1,
                MAX_RETRIES + 1,
                exc,
            )
            if attempt == MAX_RETRIES:
                break
            await asyncio.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
        else:
            return

    msg = f"Chunk {chunk_index} failed after {MAX_RETRIES} retries"
    raise RuntimeError(msg) from last_exc
