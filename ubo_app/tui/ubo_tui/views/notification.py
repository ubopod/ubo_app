"""Notification overlay view."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import ScrollableContainer
from textual.widgets import Label

from ubo_tui.views.base import BaseView
from ubo_tui.views.menu import convert_icon

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class NotificationView(BaseView):
    """Notification display view."""

    DEFAULT_CSS = """
    NotificationView {
        layout: vertical;
        padding: 1;
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
        margin-bottom: 1;
    }

    .notification-items {
        height: auto;
        max-height: 50%;
        overflow-y: auto;
    }

    .notification-item {
        height: 3;
        padding: 0 1;
        border: solid #666666;
        margin-bottom: 1;
    }

    .notification-item.selected {
        border: solid green;
        background: #003300;
    }
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._icon: str = ""
        self._title: str = "Notification"
        self._content: str = ""
        self._items: list = []
        self._item_labels: list[str] = []
        self._item_action_ids: list[str] = []
        self._selected_index: int = 0

        if view_data:
            self._icon = getattr(view_data, "icon", "") or ""
            self._title = getattr(view_data, "title", "Notification") or "Notification"
            self._content = getattr(view_data, "content", "") or ""

            # Debug logging to understand what we receive
            logger.info(
                "NotificationView.__init__: view_data type=%s",
                type(view_data).__name__,
            )
            logger.info(
                "NotificationView.__init__: icon=%r, title=%r, content=%r",
                self._icon,
                self._title,
                self._content,
            )

            # Extract items from protobuf structure
            items_container = getattr(view_data, "items", None)
            logger.info(
                "NotificationView.__init__: items_container=%r (type=%s)",
                items_container,
                type(items_container).__name__ if items_container else None,
            )
            if items_container:
                self._items = list(getattr(items_container, "items", []))
                # Pre-extract labels and action_ids for selection
                for raw_item in self._items:
                    item = raw_item
                    if hasattr(item, "items") and item.items is not None:
                        item = item.items
                    label = getattr(item, "label", "") or ""
                    action_id = getattr(item, "action_id", "") or ""
                    self._item_labels.append(label)
                    self._item_action_ids.append(action_id)
                logger.info(
                    "NotificationView.__init__: stored %d items, action_ids=%s",
                    len(self._items),
                    self._item_action_ids,
                )

    @property
    def item_count(self) -> int:
        """Return the number of action items."""
        return len(self._items)

    def get_item_label(self, index: int) -> str | None:
        """Return the label for an item at the given index."""
        if 0 <= index < len(self._item_labels):
            return self._item_labels[index]
        return None

    def get_item_action_id(self, index: int) -> str | None:
        """Return the action_id for an item at the given index."""
        if 0 <= index < len(self._item_action_ids):
            return self._item_action_ids[index]
        return None

    def compose(self) -> ComposeResult:
        """Create notification display."""
        yield Label(self._icon, classes="notification-icon")
        yield Label(self._title, classes="notification-title", markup=False)
        yield Label(self._content, classes="notification-content", markup=False)

        # Render action items if any
        if self._items:
            with ScrollableContainer(
                classes="notification-items",
                id="notification-scroll",
            ):
                for i, raw_item in enumerate(self._items):
                    if raw_item:
                        item = raw_item
                        # Handle nested item structure from protobuf
                        if hasattr(item, "items") and item.items is not None:
                            item = item.items
                        raw_icon = getattr(item, "icon", "") or ""
                        label = getattr(item, "label", "") or ""
                        icon = convert_icon(raw_icon)
                        label_text = f"{icon} {label}".strip() if label else icon
                        if i == 0:
                            classes = "notification-item selected"
                        else:
                            classes = "notification-item"
                    else:
                        label_text = "---"
                        classes = "notification-item"

                    item_id = f"notification-item-{i}"
                    yield Label(label_text, classes=classes, id=item_id, markup=False)

    def update_selection(self, index: int) -> None:
        """Update visual selection."""
        self._selected_index = index
        for i in range(len(self._items)):
            try:
                item = self.query_one(f"#notification-item-{i}", Label)
                if i == index:
                    item.add_class("selected")
                    item.scroll_visible()
                else:
                    item.remove_class("selected")
            except Exception:  # noqa: BLE001
                pass
