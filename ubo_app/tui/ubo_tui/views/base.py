"""Base view class for TUI views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widget import Widget

if TYPE_CHECKING:
    from typing import Any


class BaseView(Widget):
    """Base class for all TUI views."""

    DEFAULT_CSS = """
    BaseView {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.view_data = view_data

    def update_data(self, view_data: Any) -> None:
        """Update view with new data."""
        self.view_data = view_data
        self.refresh()
