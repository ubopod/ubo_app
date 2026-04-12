"""Server-side upload session manager for chunked file transfer."""

from __future__ import annotations

import contextlib
import math
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)

if TYPE_CHECKING:
    from ubo_app.store.services.file_upload import (
        FileUploadChunkEvent,
        FileUploadCompleteEvent,
        FileUploadStartEvent,
    )

SESSION_TTL = 600  # 10 minutes


def _upload_notification_id(upload_id: str) -> str:
    return f'file-system:upload:{upload_id}'


@dataclass
class _UploadSession:
    upload_id: str
    target_directory: str
    filename: str
    total_chunks: int
    chunk_size: int
    total_size: int
    temp_path: str
    file_handle: IO[bytes]
    received_chunks: set[int] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)


_sessions: dict[str, _UploadSession] = {}


def _fail_upload(upload_id: str, content: str) -> None:
    """Notify the user and any waiter that an upload cannot complete."""
    from ubo_app.utils.file_upload import register_failed_upload

    register_failed_upload(upload_id, content)
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=_upload_notification_id(upload_id),
                title='Upload Failed',
                content=content,
                icon='󰅙',
                display_type=NotificationDisplayType.FLASH,
                dismiss_on_close=True,
            ),
        ),
    )


def _close_and_remove_session(session: _UploadSession) -> None:
    """Close a session and remove its temporary file."""
    with contextlib.suppress(OSError):
        session.file_handle.close()
    with contextlib.suppress(OSError):
        Path(session.temp_path).unlink()


def _validate_upload_start(event: FileUploadStartEvent) -> str | None:
    if not event.upload_id:
        return 'Missing upload id'
    if event.total_size < 0:
        return 'Upload size cannot be negative'
    if event.total_size > 0 and event.chunk_size <= 0:
        return 'Upload chunk size must be positive'
    expected_chunks = (
        math.ceil(event.total_size / event.chunk_size)
        if event.total_size > 0
        else 0
    )
    if event.total_chunks != expected_chunks:
        return 'Upload metadata is invalid'
    return None


def handle_upload_start(event: FileUploadStartEvent) -> None:
    """Create a new upload session with a temp file."""
    _cleanup_stale_sessions()

    validation_error = _validate_upload_start(event)
    if validation_error:
        logger.error(
            'Invalid upload metadata',
            extra={
                'upload_id': event.upload_id,
                'total_size': event.total_size,
                'total_chunks': event.total_chunks,
                'chunk_size': event.chunk_size,
            },
        )
        _fail_upload(event.upload_id, validation_error)
        return

    if event.target_directory:
        target = Path(event.target_directory)
        if not target.is_dir():
            logger.error(
                'Upload target directory does not exist',
                extra={'target_directory': event.target_directory},
            )
            _fail_upload(
                event.upload_id,
                f'Directory does not exist: {event.target_directory}',
            )
            return

    fd, temp_path = tempfile.mkstemp(prefix='ubo_upload_')
    file_handle = os.fdopen(fd, 'wb')

    # Pre-allocate file to total_size
    if event.total_size > 0:
        file_handle.seek(event.total_size - 1)
        file_handle.write(b'\0')
        file_handle.flush()

    _sessions[event.upload_id] = _UploadSession(
        upload_id=event.upload_id,
        target_directory=event.target_directory,
        filename=event.filename,
        total_chunks=event.total_chunks,
        chunk_size=event.chunk_size,
        total_size=event.total_size,
        temp_path=temp_path,
        file_handle=file_handle,
    )

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=_upload_notification_id(event.upload_id),
                title='Uploading',
                content=f'Uploading {Path(event.filename).name}...',
                icon='󰅧',
                display_type=NotificationDisplayType.STICKY,
                progress=math.nan,
                show_dismiss_action=False,
            ),
        ),
    )

    logger.info(
        'Upload session started',
        extra={
            'upload_id': event.upload_id,
            'file_name': event.filename,
            'total_size': event.total_size,
            'total_chunks': event.total_chunks,
        },
    )


def handle_upload_chunk(event: FileUploadChunkEvent) -> None:
    """Write a chunk to the temp file at the correct offset."""
    session = _sessions.get(event.upload_id)
    if session is None:
        logger.warning(
            'Received chunk for unknown upload session',
            extra={'upload_id': event.upload_id},
        )
        return

    expected_size = (
        session.total_size - (session.total_chunks - 1) * session.chunk_size
        if event.chunk_index == session.total_chunks - 1
        else session.chunk_size
    )
    if (
        event.chunk_index < 0
        or event.chunk_index >= session.total_chunks
        or event.chunk_index in session.received_chunks
        or len(event.data) != expected_size
    ):
        logger.error(
            'Invalid upload chunk',
            extra={
                'upload_id': event.upload_id,
                'chunk_index': event.chunk_index,
                'chunk_size': len(event.data),
                'expected_size': expected_size,
                'total_chunks': session.total_chunks,
            },
        )
        _sessions.pop(event.upload_id, None)
        _close_and_remove_session(session)
        _fail_upload(event.upload_id, 'Upload chunk metadata is invalid')
        return

    offset = event.chunk_index * session.chunk_size
    session.file_handle.seek(offset)
    session.file_handle.write(event.data)
    session.file_handle.flush()
    session.received_chunks.add(event.chunk_index)

    progress = len(session.received_chunks) / session.total_chunks

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=_upload_notification_id(event.upload_id),
                title='Uploading',
                content=f'Uploading {Path(session.filename).name}...'
                f' ({len(session.received_chunks)}'
                f'/{session.total_chunks})',
                icon='󰅧',
                display_type=NotificationDisplayType.STICKY,
                progress=progress,
                show_dismiss_action=False,
            ),
        ),
    )


def handle_upload_complete(event: FileUploadCompleteEvent) -> None:
    """Finalize the upload: verify chunks and move/store file."""
    session = _sessions.pop(event.upload_id, None)
    if session is None:
        logger.warning(
            'Received complete for unknown upload session',
            extra={'upload_id': event.upload_id},
        )
        return

    session.file_handle.close()

    safe_filename = Path(session.filename).name or 'uploaded_file'

    expected_chunks = set(range(session.total_chunks))
    if session.received_chunks != expected_chunks:
        missing = len(expected_chunks - session.received_chunks)
        logger.error(
            'Upload incomplete: missing chunks',
            extra={
                'upload_id': event.upload_id,
                'missing_chunks': missing,
            },
        )
        with contextlib.suppress(OSError):
            Path(session.temp_path).unlink()
        _fail_upload(
            event.upload_id,
            f'Missing {missing} of {session.total_chunks} chunks',
        )
        return

    # Truncate file to actual total_size (last chunk may be smaller)
    with Path(session.temp_path).open('r+b') as f:
        f.truncate(session.total_size)

    if session.target_directory:
        # Move file to target directory
        destination = Path(session.target_directory) / safe_filename
        shutil.move(session.temp_path, destination)
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=_upload_notification_id(event.upload_id),
                    title='Upload Complete',
                    content=f'{safe_filename} uploaded to'
                    f' {session.target_directory}',
                    icon='󰄬',
                    display_type=NotificationDisplayType.FLASH,
                    progress=1.0,
                    dismiss_on_close=True,
                ),
            ),
        )
        logger.info(
            'Upload completed',
            extra={
                'upload_id': event.upload_id,
                'destination': destination.as_posix(),
            },
        )
    else:
        # No target directory — store temp path for caller retrieval
        from ubo_app.utils.file_upload import register_completed_upload

        register_completed_upload(event.upload_id, session.temp_path)
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=_upload_notification_id(event.upload_id),
                    title='Upload Complete',
                    content=f'{safe_filename} received',
                    icon='󰄬',
                    display_type=NotificationDisplayType.FLASH,
                    progress=1.0,
                    dismiss_on_close=True,
                ),
            ),
        )
        logger.info(
            'Upload completed (temp)',
            extra={
                'upload_id': event.upload_id,
                'temp_path': session.temp_path,
            },
        )


def _cleanup_stale_sessions() -> None:
    """Remove upload sessions older than SESSION_TTL."""
    now = time.time()
    stale = [
        uid
        for uid, session in _sessions.items()
        if now - session.created_at > SESSION_TTL
    ]
    for uid in stale:
        session = _sessions.pop(uid)
        session.file_handle.close()
        with contextlib.suppress(OSError):
            Path(session.temp_path).unlink()
        logger.warning(
            'Cleaned up stale upload session',
            extra={'upload_id': uid},
        )
