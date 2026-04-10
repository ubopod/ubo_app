"""Shared utilities for file download session management."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

SESSION_TTL = 600  # seconds


@dataclass
class DownloadSession:
    """Tracks a pending download."""

    token: str
    file_path: str
    filename: str
    is_temp: bool = False
    created_at: float = field(default_factory=time.monotonic)


_download_sessions: dict[str, DownloadSession] = {}
_pending_downloads: list[dict[str, str]] = []


def register_download(
    token: str,
    file_path: str,
    filename: str,
    *,
    is_temp: bool = False,
) -> None:
    """Register a download session for later retrieval by the HTTP endpoint."""
    _cleanup_stale_sessions()
    _download_sessions[token] = DownloadSession(
        token=token,
        file_path=file_path,
        filename=filename,
        is_temp=is_temp,
    )
    _pending_downloads.append({'token': token, 'filename': filename})


def get_pending_downloads() -> list[dict[str, str]]:
    """Return and clear the list of downloads ready for the browser."""
    result = list(_pending_downloads)
    _pending_downloads.clear()
    return result


def consume_download(token: str) -> DownloadSession | None:
    """Retrieve and remove a download session by token."""
    return _download_sessions.pop(token, None)


def _cleanup_stale_sessions() -> None:
    """Remove sessions older than SESSION_TTL and delete their temp files."""
    now = time.monotonic()
    stale = [
        tok
        for tok, session in _download_sessions.items()
        if now - session.created_at > SESSION_TTL
    ]
    for tok in stale:
        session = _download_sessions.pop(tok)
        if session.is_temp:
            Path(session.file_path).unlink(missing_ok=True)
