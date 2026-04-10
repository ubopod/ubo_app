"""Shared utilities for chunked file upload results."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ubo_app.store.main import store
from ubo_app.store.services.file_upload import FileUploadCompleteEvent

# Completed uploads: upload_id -> temp file path (for caller retrieval)
_completed_uploads: dict[str, str] = {}


def register_completed_upload(upload_id: str, temp_path: str) -> None:
    """Register a completed upload's temp file for later retrieval."""
    _completed_uploads[upload_id] = temp_path


def get_completed_upload(upload_id: str) -> str | None:
    """Retrieve and consume the temp path of a completed upload."""
    return _completed_uploads.pop(upload_id, None)


async def await_completed_upload(upload_id: str) -> bytes:
    """Wait for a chunked upload to complete, then read and return bytes."""
    loop = asyncio.get_event_loop()
    done: asyncio.Future[bool] = loop.create_future()

    def _on_complete(event: FileUploadCompleteEvent) -> None:
        if event.upload_id == upload_id and not done.done():
            loop.call_soon_threadsafe(done.set_result, True)

    # Subscribe BEFORE checking to avoid a race where the event fires between
    # the check and the subscription, which would cause an indefinite hang.
    unsubscribe = store.subscribe_event(
        FileUploadCompleteEvent,
        _on_complete,
    )

    try:
        # Now check if already completed (covers the case where the upload
        # finished before we subscribed).
        temp_path = get_completed_upload(upload_id)
        if temp_path:
            data = Path(temp_path).read_bytes()
            Path(temp_path).unlink(missing_ok=True)
            return data

        await done
    finally:
        unsubscribe()

    temp_path = get_completed_upload(upload_id)
    if temp_path is None:
        msg = f'No completed upload with id {upload_id}'
        raise FileNotFoundError(msg)
    data = Path(temp_path).read_bytes()
    Path(temp_path).unlink(missing_ok=True)
    return data
