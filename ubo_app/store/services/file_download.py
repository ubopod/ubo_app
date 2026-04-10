"""File download store types for transferring files from device to browser."""

from __future__ import annotations

from redux import BaseEvent

from ubo_app.store.services.file_system import FileSystemAction


class FileDownloadAction(FileSystemAction):
    """Base action for file download operations."""


class FileDownloadRequestAction(FileDownloadAction):
    """Request a file or directory download."""

    path: str


class FileDownloadReadyAction(FileDownloadAction):
    """Signal that a download is ready for the browser to fetch."""

    download_token: str
    filename: str


class FileDownloadEvent(BaseEvent):
    """Base event for file download operations."""


class FileDownloadRequestEvent(FileDownloadEvent):
    """Event emitted when a download is requested."""

    path: str


class FileDownloadReadyEvent(FileDownloadEvent):
    """Event emitted when a download is ready to fetch."""

    download_token: str
    filename: str
