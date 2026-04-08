"""File system store types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.input.types import PathInputDescription


class PathSelectorConfig(Immutable):
    """Configuration for the path selector."""

    initial_path: str | None = None
    show_hidden: bool = False
    accepts_files: bool | None = None
    accepts_directories: bool | None = None
    acceptable_suffixes: Sequence[str] | None = None


class FileSystemAction(BaseAction):
    """Base action for file system operations."""


class FileSystemReportSelectionAction(FileSystemAction):
    """Report a file system selection."""

    path: str


class FileSystemSelectorPushedAction(FileSystemAction):
    """Track when a menu is pushed during selector navigation."""


class FileSystemCopyAction(FileSystemAction):
    """Copy files or directories to a new location."""

    sources: Sequence[str]
    destination: str


class FileSystemMoveAction(FileSystemAction):
    """Move files or directories to a new location."""

    sources: Sequence[str]
    destination: str


class FileSystemRemoveAction(FileSystemAction):
    """Remove files or directories."""

    paths: Sequence[str]


class FileSystemEvent(BaseEvent):
    """Base event for file system operations."""


class FileSystemSelectEvent(FileSystemEvent):
    """Event for opening the path selector."""

    description: PathInputDescription


class FileSystemCopyEvent(FileSystemEvent):
    """Event for copying filesystem items."""

    sources: Sequence[str]
    destination: str


class FileSystemMoveEvent(FileSystemEvent):
    """Event for moving filesystem items."""

    sources: Sequence[str]
    destination: str


class FileSystemRemoveEvent(FileSystemEvent):
    """Event for removing filesystem items."""

    paths: Sequence[str]


class FileSystemSelectorCleanupEvent(FileSystemEvent):
    """Event emitted when selector mode ends (success or cancel).

    Subscribers should restore browse-mode menus and clean up selector state.
    """


class FileSystemState(Immutable):
    """State for the file system service."""

    current_input: PathInputDescription | None = None
    queue: list[PathInputDescription]
    selector_depth: int = 0
