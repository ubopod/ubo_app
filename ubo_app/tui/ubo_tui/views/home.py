"""Home view with CPU/RAM gauges and volume."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ProgressBar

from ubo_tui.views.base import BaseView

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class HomeView(BaseView):
    """Home screen with system metrics and menu items."""

    DEFAULT_CSS = """
    HomeView {
        layout: vertical;
        padding: 1;
    }

    .metrics {
        height: auto;
        margin-bottom: 1;
    }

    .metric-row {
        height: 3;
    }

    .metric-label {
        width: 8;
    }

    .menu-items {
        height: auto;
        margin-top: 1;
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
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._cpu_percent: float = 0.0
        self._ram_percent: float = 0.0
        self._volume_level: float = 0.0
        self._items: list = []
        self._item_labels: list[str] = []
        self._selected_index: int = 0

        if view_data:
            self._cpu_percent = getattr(view_data, "cpu_percent", 0.0) or 0.0
            self._ram_percent = getattr(view_data, "ram_percent", 0.0) or 0.0
            self._volume_level = getattr(view_data, "volume_level", 0.0) or 0.0

            # Extract menu items from view data
            menu_items_container = getattr(view_data, "menu_items", None)
            if menu_items_container:
                self._items = list(getattr(menu_items_container, "items", []))
                # Pre-extract labels for selection by label (use server labels)
                for raw_item in self._items:
                    item = raw_item
                    if hasattr(item, "items") and item.items is not None:
                        item = item.items
                    label = getattr(item, "label", "") or ""
                    self._item_labels.append(label)
                logger.info(
                    "HomeView.__init__: stored %d labels: %r",
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
        with Vertical(classes="metrics"):
            with Horizontal(classes="metric-row"):
                yield Label("CPU:", classes="metric-label")
                yield ProgressBar(total=100, show_eta=False, id="cpu-gauge")

            with Horizontal(classes="metric-row"):
                yield Label("RAM:", classes="metric-label")
                yield ProgressBar(total=100, show_eta=False, id="ram-gauge")

            with Horizontal(classes="metric-row"):
                yield Label("Vol:", classes="metric-label")
                yield ProgressBar(total=100, show_eta=False, id="volume-gauge")

        # Fallback labels for home menu items
        fallback_labels = ["Menu", "Notifications", "Power"]

        with Vertical(classes="menu-items"):
            for i, raw_item in enumerate(self._items):
                if raw_item:
                    item = raw_item
                    if hasattr(item, "items") and item.items is not None:
                        item = item.items
                    icon = getattr(item, "icon", "") or ""
                    label = getattr(item, "label", "") or ""
                    # Use fallback label if server label is empty
                    if not label and i < len(fallback_labels):
                        label = fallback_labels[i]
                    label_text = f"{icon} {label}".strip()
                    classes = "menu-item selected" if i == 0 else "menu-item"
                else:
                    # Use fallback for empty items
                    label = fallback_labels[i] if i < len(fallback_labels) else "---"
                    label_text = label
                    classes = "menu-item"
                yield Label(label_text, classes=classes, id=f"menu-item-{i}")

    def on_mount(self) -> None:
        """Update gauges after mounting."""
        self._update_gauges()

    def _update_gauges(self) -> None:
        """Update gauge values."""
        try:
            cpu_gauge = self.query_one("#cpu-gauge", ProgressBar)
            cpu_gauge.progress = self._cpu_percent
        except Exception:  # noqa: BLE001
            pass

        try:
            ram_gauge = self.query_one("#ram-gauge", ProgressBar)
            ram_gauge.progress = self._ram_percent
        except Exception:  # noqa: BLE001
            pass

        try:
            vol_gauge = self.query_one("#volume-gauge", ProgressBar)
            vol_gauge.progress = self._volume_level * 100
        except Exception:  # noqa: BLE001
            pass

    def update_selection(self, index: int) -> None:
        """Update visual selection."""
        self._selected_index = index
        for i in range(len(self._items)):
            try:
                item = self.query_one(f"#menu-item-{i}", Label)
                if i == index:
                    item.add_class("selected")
                else:
                    item.remove_class("selected")
            except Exception:  # noqa: BLE001
                pass

    def update_data(self, view_data: Any) -> None:
        """Update gauges with new values."""
        self.view_data = view_data

        if view_data:
            self._cpu_percent = getattr(view_data, "cpu_percent", 0.0) or 0.0
            self._ram_percent = getattr(view_data, "ram_percent", 0.0) or 0.0
            self._volume_level = getattr(view_data, "volume_level", 0.0) or 0.0

        self._update_gauges()
