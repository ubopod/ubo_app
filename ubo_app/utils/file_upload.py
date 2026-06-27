"""Shared utilities for chunked file upload results."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

_DEFAULT_UPLOAD_TIMEOUT = 120.0


def _upload_timeout() -> float:
    """Backstop so a coroutine never blocks forever when the client dies mid-upload.

    (Dispatch fails client-side, so no completion/failure is ever registered.)
    Read at call time and tolerant of a malformed env value so it can't crash
    module import.
    """
    try:
        return float(os.environ.get('UBO_UPLOAD_TIMEOUT', str(_DEFAULT_UPLOAD_TIMEOUT)))
    except (TypeError, ValueError):
        return _DEFAULT_UPLOAD_TIMEOUT

# Completed uploads: upload_id -> temp file path (for caller retrieval)
_completed_uploads: dict[str, str] = {}
_failed_uploads: dict[str, str] = {}

# Waiters: upload_id -> (loop, future) for coroutines awaiting completion
_upload_waiters: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Future[bool]]] = {}
_lock = threading.Lock()


def register_completed_upload(upload_id: str, temp_path: str) -> None:
    """Register a completed upload's temp file for later retrieval."""
    with _lock:
        _completed_uploads[upload_id] = temp_path
        _failed_uploads.pop(upload_id, None)
        waiter = _upload_waiters.pop(upload_id, None)
    if waiter:
        loop, future = waiter
        loop.call_soon_threadsafe(_resolve_future, future)


def register_failed_upload(upload_id: str, reason: str) -> None:
    """Register an upload failure and wake any coroutine awaiting it."""
    with _lock:
        _failed_uploads[upload_id] = reason
        waiter = _upload_waiters.pop(upload_id, None)
    if waiter:
        loop, future = waiter
        loop.call_soon_threadsafe(_set_future_exception, future, RuntimeError(reason))


def _resolve_future(future: asyncio.Future[bool]) -> None:
    """Resolve a future if it has not already been cancelled."""
    if not future.done():
        future.set_result(True)


def _set_future_exception(future: asyncio.Future[bool], exception: Exception) -> None:
    """Reject a future if it has not already been cancelled."""
    if not future.done():
        future.set_exception(exception)


def get_completed_upload(upload_id: str) -> str | None:
    """Retrieve and consume the temp path of a completed upload."""
    with _lock:
        return _completed_uploads.pop(upload_id, None)


async def await_completed_upload(
    upload_id: str,
    *,
    timeout: float | None = None,  # noqa: ASYNC109 — deliberate env-overridable backstop
) -> bytes:
    """Wait for a chunked upload to complete, then read and return bytes."""
    loop = asyncio.get_event_loop()
    done: asyncio.Future[bool] = loop.create_future()

    with _lock:
        # Check if already completed before registering waiter. Only the dict
        # ops run under the lock; file I/O happens outside it (below).
        temp_path = _completed_uploads.pop(upload_id, None)
        failure_reason = None if temp_path else _failed_uploads.pop(upload_id, None)
        if temp_path is None and failure_reason is None:
            _upload_waiters[upload_id] = (loop, done)

    if temp_path is not None:
        data = Path(temp_path).read_bytes()
        Path(temp_path).unlink(missing_ok=True)
        return data
    if failure_reason is not None:
        raise RuntimeError(failure_reason)

    try:
        await asyncio.wait_for(
            done,
            timeout if timeout is not None else _upload_timeout(),
        )
    except TimeoutError as exception:
        msg = f'Upload {upload_id} did not complete in time'
        raise RuntimeError(msg) from exception
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
