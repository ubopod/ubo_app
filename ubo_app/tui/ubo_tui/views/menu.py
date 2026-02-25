"""Menu list view."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import ScrollableContainer
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
    """Standard menu view with title, items, and scrollable list."""

    DEFAULT_CSS = """
    MenuView {
        layout: vertical;
        padding: 1;
    }

    .menu-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 0;
        height: 3;
    }

    .menu-heading {
        text-align: center;
        text-style: bold;
        color: #aaaaff;
        margin-bottom: 0;
        height: auto;
    }

    .menu-sub-heading {
        text-align: center;
        color: #888888;
        margin-bottom: 1;
        height: auto;
    }

    .menu-items {
        height: 1fr;
        overflow-y: auto;
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
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._title: str = ""
        self._heading: str | None = None
        self._sub_heading: str | None = None
        self._items: list = []
        self._item_labels: list[str] = []
        self._selected_index: int = 0

        if view_data:
            self._title = getattr(view_data, "title", "") or ""
            self._heading = getattr(view_data, "heading", None) or None
            self._sub_heading = getattr(view_data, "sub_heading", None) or None

            # Extract items from protobuf structure
            items_container = getattr(view_data, "items", None)
            if items_container:
                self._items = list(getattr(items_container, "items", []))
                # Pre-extract labels for selection by label
                for raw_item in self._items:
                    item = raw_item
                    if hasattr(item, "items") and item.items is not None:
                        item = item.items
                    label = getattr(item, "label", "") or ""
                    self._item_labels.append(label)
                logger.info(
                    "MenuView.__init__: stored %d labels: %r",
                    len(self._item_labels),
                    self._item_labels,
                )

    @property
    def item_count(self) -> int:
        """Return the number of menu items."""
        return len(self._items)

    def get_item_label(self, index: int) -> str | None:
        """Return the label for an item at the given index."""
        if 0 <= index < len(self._item_labels):
            return self._item_labels[index]
        return None

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        logger.info(
            "MenuView.compose: title=%s, heading=%s, sub_heading=%s, items=%d",
            self._title,
            self._heading,
            self._sub_heading,
            len(self._items),
        )
        yield Label(self._title, classes="menu-title")

        # Display heading and sub_heading for HeadedMenu
        if self._heading:
            yield Label(self._heading, classes="menu-heading")
        if self._sub_heading:
            # Strip any color markup (e.g., [color=...]...[/color]) for TUI
            sub_heading_text = self._strip_color_markup(self._sub_heading)
            yield Label(sub_heading_text, classes="menu-sub-heading")

        with ScrollableContainer(classes="menu-items", id="menu-scroll"):
            for i, raw_item in enumerate(self._items):
                if raw_item:
                    item = raw_item
                    logger.info(
                        "  Raw item %d: type=%s, attrs=%s",
                        i,
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
                        i,
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

    def _strip_color_markup(self, text: str) -> str:
        """Strip color markup tags from text.

        Handles [color=...]...[/color] and similar BBCode-style tags.
        """
        import re

        # Remove [color=...]...[/color] tags but keep the content
        result = re.sub(r"\[color=[^\]]*\]", "", text)
        result = re.sub(r"\[/color\]", "", result)
        # Remove other common BBCode-style tags
        result = re.sub(r"\[/?[a-z]+\]", "", result)
        return result.strip()

    def update_selection(self, index: int) -> None:
        """Update visual selection and scroll to keep it visible."""
        self._selected_index = index
        for i in range(len(self._items)):
            try:
                item = self.query_one(f"#menu-item-{i}", Label)
                if i == index:
                    item.add_class("selected")
                    item.scroll_visible()
                else:
                    item.remove_class("selected")
            except Exception:  # noqa: BLE001
                pass
