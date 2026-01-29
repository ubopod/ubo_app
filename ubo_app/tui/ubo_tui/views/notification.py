"""Notification overlay view."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Label

from ubo_tui.views.base import BaseView

if TYPE_CHECKING:
    from textual.app import ComposeResult


class NotificationView(BaseView):
    """Notification display view."""

    DEFAULT_CSS = """
    NotificationView {
        layout: vertical;
        padding: 2;
        border: double red;
        align: center middle;
    }

    .notification-icon {
        text-align: center;
        height: 3;
    }

    .notification-title {
        text-align: center;
        text-style: bold;
        margin: 1;
    }

    .notification-content {
        text-align: center;
    }
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._icon: str = ""
        self._title: str = "Notification"
        self._content: str = ""

        if view_data:
            self._icon = getattr(view_data, "icon", "") or ""
            self._title = getattr(view_data, "title", "Notification") or "Notification"
            self._content = getattr(view_data, "content", "") or ""

    def compose(self) -> ComposeResult:
        """Create notification display."""
        yield Label(self._icon, classes="notification-icon")
        yield Label(self._title, classes="notification-title")
        yield Label(self._content, classes="notification-content")
