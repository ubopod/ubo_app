"""Menu list view."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.widgets import Label

from ubo_tui.views.base import BaseView

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)

# ASCII range boundary (characters above this are non-ASCII/unicode)
ASCII_MAX = 127

# Nerd font to ASCII fallback mapping for terminals without nerd fonts
# These are the actual icons used in ubo_app (from utils/gui/__init__.py and services)
ICON_FALLBACK: dict[str, str] = {
    # Checkbox icons (from SELECTED/UNSELECTED_ITEM_PARAMETERS)
    "󰱒": "[x]",  # Selected checkbox (U+F0C52)
    "󰄱": "[ ]",  # Unselected checkbox (U+F0131)
    # Menu icons
    "󰍜": "[=]",  # Menu/hamburger
    "󰂞": "[!]",  # Notification bell
    "󰐥": "[P]",  # Power
    # Action icons
    "󰓛": "[S]",  # Stop
    "󰐊": "[>]",  # Play/Start
    "󰯄": "[-]",  # Disable
    "󰯅": "[+]",  # Enable
    "󰍃": "[<]",  # Logout/back
    "󰍂": "[>]",  # Login
    "󰇚": "[D]",  # Download
    "󰶮": "[I]",  # Install
    "󰀔": "[+]",  # Add user
    "󰀄": "[U]",  # User
    "󰐲": "[Q]",  # QR/URL
    # Other common icons
    "": "",  # Speech recognition
    "\ue615": "[*]",  # Deepgram/AssemblyAI icon
}


def convert_icon(icon: str, *, use_ascii_fallback: bool = False) -> str:
    """Convert nerd font icon to ASCII fallback if needed.

    Args:
        icon: The icon string to convert
        use_ascii_fallback: If True, convert to ASCII. If False, pass through
            the original icon (for terminals with Nerd Fonts installed).
    """
    if not icon:
        return ""
    if not use_ascii_fallback:
        # Pass through - terminal has nerd fonts installed
        return icon
    # ASCII fallback mode for terminals without nerd fonts
    if icon in ICON_FALLBACK:
        return ICON_FALLBACK[icon]
    # For unknown icons, check if it's a non-ASCII character
    if ord(icon[0]) > ASCII_MAX:
        return "[?]"
    return icon


class MenuView(BaseView):
    """Standard menu view with title, items, and pagination."""

    DEFAULT_CSS = """
    MenuView {
        layout: vertical;
        padding: 1;
    }

    .menu-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
        height: 3;
    }

    .menu-items {
        height: auto;
    }

    .menu-item {
        height: 3;
        padding: 0 1;
        border: solid #666666;
        margin-bottom: 1;
    }

    .menu-item.selected {
        border: solid green;
        background: #003300;
    }

    .menu-item.empty {
        border: dashed #333333;
        color: #666666;
    }

    .pagination {
        text-align: center;
        margin-top: 1;
        height: 1;
    }
    """

    # Number of items to display per page
    PAGE_SIZE = 3

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._title: str = ""
        self._items: list = []
        self._page_index: int = 0
        self._total_pages: int = 1

        if view_data:
            self._title = getattr(view_data, "title", "") or ""

            # Extract items from protobuf structure
            items_container = getattr(view_data, "items", None)
            if items_container:
                self._items = list(getattr(items_container, "items", []))

            # Compute total pages from actual item count (ceiling division)
            item_count = len(self._items)
            pages = (item_count + self.PAGE_SIZE - 1) // self.PAGE_SIZE
            self._total_pages = max(1, pages)

            # Get page_index from server and cap to valid range
            raw_page_index = getattr(view_data, "page_index", 0) or 0
            self._page_index = max(0, min(raw_page_index, self._total_pages - 1))

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        logger.info(
            "MenuView.compose: title=%s, items=%d",
            self._title,
            len(self._items),
        )
        yield Label(self._title, classes="menu-title")

        with Vertical(classes="menu-items"):
            # Server sends all items; paginate locally based on page_index
            start = self._page_index * self.PAGE_SIZE
            for i in range(self.PAGE_SIZE):
                item_index = start + i
                if item_index < len(self._items) and self._items[item_index]:
                    item = self._items[item_index]
                    logger.info(
                        "  Raw item %d: type=%s, attrs=%s",
                        item_index,
                        type(item).__name__,
                        dir(item)[:10],
                    )
                    # Handle nested item structure from protobuf
                    # MenuViewDataItemsItem wraps MenuItemData in .items field
                    if hasattr(item, "items") and item.items is not None:
                        item = item.items
                    raw_icon = getattr(item, "icon", "") or ""
                    label = getattr(item, "label", "") or ""
                    icon = convert_icon(raw_icon)
                    logger.info(
                        "  Item %d: raw_icon=%r, icon=%r, label=%r",
                        item_index,
                        raw_icon,
                        icon,
                        label,
                    )
                    label_text = f"{icon} {label}".strip()
                    classes = "menu-item selected" if i == 0 else "menu-item"
                else:
                    label_text = "---"
                    classes = "menu-item empty"

                yield Label(label_text, classes=classes, id=f"menu-item-{i}")

        if self._total_pages > 1:
            yield Label(
                f"Page {self._page_index + 1}/{self._total_pages}",
                classes="pagination",
            )

    def update_selection(self, index: int) -> None:
        """Update visual selection."""
        for i in range(self.PAGE_SIZE):
            try:
                item = self.query_one(f"#menu-item-{i}", Label)
                if i == index:
                    item.add_class("selected")
                else:
                    item.remove_class("selected")
            except Exception:  # noqa: BLE001
                pass
