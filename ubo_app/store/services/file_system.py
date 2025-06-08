"""File system store types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ubo_app.store.input.types import PathInputDescription


class PathSelectorConfig(Immutable):
    """Configuration for the path selector."""

    initial_path: Path | None = None
    show_hidden: bool = False
    accepts_files: bool | None = None
    accepts_directories: bool | None = None
    acceptable_suffixes: Sequence[str] | None = None


class FileSystemAction(BaseAction):
    """Base action for file system operations."""


class FileSystemReportSelectionAction(FileSystemAction):
    """Report a file system selection."""

    path: Path


class FileSystemEvent(BaseEvent):
    """Base event for file system operations."""


class FileSystemSelectEvent(FileSystemEvent):
    """Event for opening the path selector."""

    description: PathInputDescription


class FileSystemState(Immutable):
    """State for the file system service."""

    current_input: PathInputDescription | None = None
    queue: list[PathInputDescription]
