"""A module to track imports of other modules."""

from __future__ import annotations

import importlib.abc
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import ModuleType


class ImportTracker(importlib.abc.MetaPathFinder):
    """A meta path finder that tracks imports."""

    def __init__(self: ImportTracker, modules: Sequence[str]) -> None:
        """Initialize the import tracker."""
        self.modules = modules
        self.imported_modules = {}
        super().__init__()

    def find_spec(
        self: ImportTracker,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> None:
        """Find a module spec for the given module."""
        _ = (path, target)
        if fullname not in self.imported_modules:
            self.imported_modules[fullname] = 0
        self.imported_modules[fullname] += 1


@dataclass
class Tracker:
    """Return type for the install_tracker function."""

    uninstall: Callable[[], None]
    check: Callable[[str], bool]
    imported_modules: dict[str, int]


def install_tracker(modules: Sequence[str]) -> Tracker:
    """Install the import tracker."""
    import_tracker = ImportTracker(modules)

    sys.meta_path.insert(0, import_tracker)

    def uninstall_tracker() -> None:
        """Uninstall the import tracker."""
        sys.meta_path.remove(import_tracker)

    def was_module_imported(module_name: str) -> bool:
        """Check if a module was imported."""
        return module_name in import_tracker.imported_modules

    return Tracker(
        uninstall=uninstall_tracker,
        check=was_module_imported,
        imported_modules=import_tracker.imported_modules,
    )
