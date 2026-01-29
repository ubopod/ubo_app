"""Home view with CPU/RAM gauges and volume."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ProgressBar

from ubo_tui.views.base import BaseView

if TYPE_CHECKING:
    from textual.app import ComposeResult


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
        border: solid green;
        margin-bottom: 1;
    }

    .menu-item:focus {
        border: solid yellow;
    }
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._cpu_percent: float = 0.0
        self._ram_percent: float = 0.0
        self._volume_level: float = 0.0

        if view_data:
            self._cpu_percent = getattr(view_data, "cpu_percent", 0.0) or 0.0
            self._ram_percent = getattr(view_data, "ram_percent", 0.0) or 0.0
            self._volume_level = getattr(view_data, "volume_level", 0.0) or 0.0

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

        with Vertical(classes="menu-items"):
            # Home has 3 fixed items: Main, Notifications, Power
            # Using ASCII fallbacks for terminal compatibility
            yield Label("[=] Main", classes="menu-item", id="menu-item-0")
            yield Label("[!] Notifications", classes="menu-item", id="menu-item-1")
            yield Label("[P] Power", classes="menu-item", id="menu-item-2")

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

    def update_data(self, view_data: Any) -> None:
        """Update gauges with new values."""
        self.view_data = view_data

        if view_data:
            self._cpu_percent = getattr(view_data, "cpu_percent", 0.0) or 0.0
            self._ram_percent = getattr(view_data, "ram_percent", 0.0) or 0.0
            self._volume_level = getattr(view_data, "volume_level", 0.0) or 0.0

        self._update_gauges()
