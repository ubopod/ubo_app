"""File system store types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from immutable import Immutable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class PathSelectorConfig(Immutable):
    """Configuration for the path selector."""

    initial_path: Path | None = None
    show_hidden: bool = False
    accepts_files: bool | None = None
    accepts_directories: bool | None = None
    acceptable_suffixes: Sequence[str] | None = None
