"""Application view placeholder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Label

from ubo_tui.views.base import BaseView

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ApplicationView(BaseView):
    """Placeholder for application views."""

    DEFAULT_CSS = """
    ApplicationView {
        layout: vertical;
        padding: 2;
        align: center middle;
    }

    .app-id {
        text-align: center;
        text-style: bold;
    }

    .app-notice {
        text-align: center;
        color: #888888;
        margin-top: 1;
    }
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._app_id: str = "unknown"

        if view_data:
            self._app_id = (
                getattr(
                    view_data,
                    "application_id",
                    getattr(view_data, "kind", "unknown"),
                )
                or "unknown"
            )

    def compose(self) -> ComposeResult:
        """Show application ID."""
        yield Label(f"Application: {self._app_id}", classes="app-id")
        yield Label("(TUI does not support applications yet)", classes="app-notice")
