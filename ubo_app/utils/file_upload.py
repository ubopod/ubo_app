"""Shared utilities for chunked file upload results."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

# Completed uploads: upload_id -> temp file path (for caller retrieval)
_completed_uploads: dict[str, str] = {}

# Waiters: upload_id -> (loop, future) for coroutines awaiting completion
_upload_waiters: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Future[bool]]] = {}
_lock = threading.Lock()


def register_completed_upload(upload_id: str, temp_path: str) -> None:
    """Register a completed upload's temp file for later retrieval."""
    with _lock:
        _completed_uploads[upload_id] = temp_path
        waiter = _upload_waiters.pop(upload_id, None)
    if waiter:
        loop, future = waiter
        loop.call_soon_threadsafe(future.set_result, True)  # noqa: FBT003


def get_completed_upload(upload_id: str) -> str | None:
    """Retrieve and consume the temp path of a completed upload."""
    with _lock:
        return _completed_uploads.pop(upload_id, None)


async def await_completed_upload(upload_id: str) -> bytes:
    """Wait for a chunked upload to complete, then read and return bytes."""
    loop = asyncio.get_event_loop()
    done: asyncio.Future[bool] = loop.create_future()

    with _lock:
        # Check if already completed before registering waiter
        temp_path = _completed_uploads.pop(upload_id, None)
        if temp_path:
            data = Path(temp_path).read_bytes()
            Path(temp_path).unlink(missing_ok=True)
            return data
        _upload_waiters[upload_id] = (loop, done)

    try:
        await done
    finally:
        with _lock:
            _upload_waiters.pop(upload_id, None)

    temp_path = get_completed_upload(upload_id)
    if temp_path is None:
        msg = f'No completed upload with id {upload_id}'
        raise FileNotFoundError(msg)
    data = Path(temp_path).read_bytes()
    Path(temp_path).unlink(missing_ok=True)
    return data
