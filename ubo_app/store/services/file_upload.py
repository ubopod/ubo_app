"""File upload store types for chunked file transfer over gRPC."""

from __future__ import annotations

from redux import BaseAction, BaseEvent


class FileUploadAction(BaseAction):
    """Base action for file upload operations."""


class FileUploadStartAction(FileUploadAction):
    """Start a chunked file upload session."""

    upload_id: str
    target_directory: str = ''
    filename: str = ''
    total_size: int = 0
    total_chunks: int = 0
    chunk_size: int = 0


class FileUploadChunkAction(FileUploadAction):
    """Upload a single chunk of a file."""

    upload_id: str
    chunk_index: int
    data: bytes


class FileUploadCompleteAction(FileUploadAction):
    """Signal that all chunks have been sent."""

    upload_id: str


class FileUploadEvent(BaseEvent):
    """Base event for file upload operations."""


class FileUploadStartEvent(FileUploadEvent):
    """Event emitted when an upload session starts."""

    upload_id: str
    target_directory: str = ''
    filename: str = ''
    total_size: int = 0
    total_chunks: int = 0
    chunk_size: int = 0


class FileUploadChunkEvent(FileUploadEvent):
    """Event emitted when a chunk is received."""

    upload_id: str
    chunk_index: int
    data: bytes


class FileUploadCompleteEvent(FileUploadEvent):
    """Event emitted when all chunks are acknowledged."""

    upload_id: str


class FileUploadErrorEvent(FileUploadEvent):
    """Event emitted when an upload fails."""

    upload_id: str
    error: str
