"""Loading view shown while syncing with server."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Label, LoadingIndicator

from ubo_tui.views.base import BaseView

if TYPE_CHECKING:
    from typing import Any

    from textual.app import ComposeResult


class LoadingView(BaseView):
    """Loading placeholder shown before initial state sync."""

    DEFAULT_CSS = """
    LoadingView {
        layout: vertical;
        align: center middle;
    }

    .loading-text {
        text-align: center;
        margin-bottom: 1;
    }
    """

    def __init__(self, view_data: Any = None, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)

    def compose(self) -> ComposeResult:
        """Show loading indicator."""
        yield Label("Connecting to Ubo...", classes="loading-text")
        yield LoadingIndicator()
