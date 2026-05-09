"""Status bar widget (header and footer)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal
from textual.widgets import Label, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)

# ASCII range boundary (characters above this are non-ASCII/unicode)
ASCII_MAX = 127

# Status bar icon fallbacks for terminals without nerd fonts
STATUS_ICON_FALLBACK: dict[str, str] = {
    # WiFi signal strength icons
    "󰤯": "w",  # WiFi weak (0-20%)
    "󰤟": "W",  # WiFi low (20-40%)
    "󰤢": "W",  # WiFi medium (40-60%)
    "󰤥": "W",  # WiFi good (60-80%)
    "󰤨": "W",  # WiFi strong (80-100%)
    "󰖪": "x",  # WiFi disconnected
    "󰤭": "x",  # WiFi disconnected (alternate)
    # Internet/Globe icons
    "󰖟": "@",  # Globe/Internet connected
    "󰪎": "!",  # Globe/Internet disconnected
    # Ethernet icons
    "󱊪": "E",  # Ethernet connected
    "󰌙": "e",  # Ethernet disconnected
    "󰈀": "E",  # Ethernet (alternate)
    # Microphone icons
    "󰍭": "m",  # Microphone muted
    "󰍬": "M",  # Microphone unmuted
    # Battery icons
    "󰂄": "B",  # Battery charging
    "󰁹": "B",  # Battery full
    "󰂃": "b",  # Battery low
    "󱊡": "b",  # Battery empty
    # Notification/Warning icons
    "󰋼": "!",  # Info/notification
    "": "!",  # Warning
    "󰍜": "=",  # Menu
}


def convert_status_icon(symbol: str) -> str:
    """Convert nerd font status icon to ASCII fallback."""
    if not symbol:
        return ""
    if symbol in STATUS_ICON_FALLBACK:
        return STATUS_ICON_FALLBACK[symbol]
    # For unknown non-ASCII icons, return a placeholder
    if ord(symbol[0]) > ASCII_MAX:
        return "*"
    return symbol


# Progress bar rendering width (number of cells between the brackets).
PROGRESS_BAR_WIDTH = 10


def _render_progress_bar(progress: float | None, *, width: int = PROGRESS_BAR_WIDTH) -> str:
    """Render a single inline ASCII progress bar.

    Determinate (``0.0 <= progress <= 1.0``) → ``[██████░░░░] 60%``.
    Indeterminate (``progress is None``)     → ``[··········]`` (no percent).
    """
    if width <= 0:
        return ""
    if progress is None:
        return "[" + ("·" * width) + "]"
    # Clamp + ignore NaN (proto field can be float NaN).
    if progress != progress:  # NaN check
        return "[" + ("·" * width) + "]"
    clamped = max(0.0, min(1.0, progress))
    filled = int(round(clamped * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {int(round(clamped * 100))}%"


def _render_progress_label(progress_notifications: list) -> str:
    """Render the footer's progress portion from a list of ProgressNotificationData.

    Shows the first entry; for >1 entries, appends ``(+N more)`` to keep the
    footer to a single line.
    """
    if not progress_notifications:
        return ""
    first = progress_notifications[0]
    progress = getattr(first, "progress", None)
    text = _render_progress_bar(progress)
    extras = len(progress_notifications) - 1
    if extras > 0:
        text = f"{text} (+{extras} more)"
    return text


class HeaderBar(Static):
    """Header bar with title and indicators."""

    DEFAULT_CSS = """
    HeaderBar {
        dock: top;
        height: 1;
        background: #1a1a2e;
        padding: 0 1;
    }

    .header-content {
        width: 100%;
    }

    .title {
        width: 1fr;
    }

    .indicators {
        width: auto;
    }

    .recording {
        color: red;
    }
    """

    def __init__(self, status_bar_data: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.status_bar_data = status_bar_data

    def compose(self) -> ComposeResult:
        """Create header content."""
        with Horizontal(classes="header-content"):
            yield Label("Ubo", classes="title", id="header-title")
            yield Label("", classes="indicators", id="header-indicators")

    def update_data(self, data: Any) -> None:
        """Update header with new status bar data."""
        self.status_bar_data = data
        if data:
            indicators = []
            if getattr(data, "is_recording", False):
                indicators.append("[REC]")
            if getattr(data, "is_replaying", False):
                indicators.append("[PLAY]")
            if getattr(data, "is_recording_audio", False):
                indicators.append("[MIC]")

            try:
                ind_label = self.query_one("#header-indicators", Label)
                ind_label.update(" ".join(indicators))
            except Exception:  # noqa: BLE001
                pass


class FooterBar(Static):
    """Footer bar with clock, temp, and icons."""

    DEFAULT_CSS = """
    FooterBar {
        dock: bottom;
        height: 1;
        background: #1a1a2e;
        padding: 0 1;
    }

    .footer-content {
        width: 100%;
    }

    .clock {
        width: auto;
        margin-right: 2;
    }

    .temp {
        width: auto;
        margin-right: 2;
    }

    .progress {
        width: auto;
        margin-right: 2;
    }

    .icons {
        width: 1fr;
        text-align: right;
    }
    """

    def __init__(self, status_bar_data: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.status_bar_data = status_bar_data

    def compose(self) -> ComposeResult:
        """Create footer content."""
        with Horizontal(classes="footer-content"):
            yield Label("--:--", classes="clock", id="footer-clock")
            yield Label("--.-C", classes="temp", id="footer-temp")
            yield Label("", classes="progress", id="footer-progress")
            yield Label("", classes="icons", id="footer-icons")

    def update_data(self, data: Any) -> None:
        """Update footer with new status bar data."""
        self.status_bar_data = data
        if data:
            try:
                clock_label = self.query_one("#footer-clock", Label)
                clock_val = getattr(data, "clock", "--:--") or "--:--"
                clock_label.update(clock_val)
            except Exception:  # noqa: BLE001
                pass

            try:
                temp_label = self.query_one("#footer-temp", Label)
                temp = getattr(data, "temperature", None)
                temp_label.update(f"{temp:.1f}C" if temp else "--.-C")
            except Exception:  # noqa: BLE001
                pass

            try:
                progress_label = self.query_one("#footer-progress", Label)
                progress_container = getattr(data, "progress_notifications", None)
                if progress_container is not None:
                    items = list(getattr(progress_container, "items", []) or [])
                else:
                    items = []
                progress_label.update(_render_progress_label(items))
            except Exception:  # noqa: BLE001
                pass

            try:
                icons_label = self.query_one("#footer-icons", Label)
                icons_container = getattr(data, "icons", None)
                if icons_container:
                    icons = list(getattr(icons_container, "items", []))
                    logger.info(
                        "Footer icons: %d items",
                        len(icons),
                    )
                    for idx, icon in enumerate(icons):
                        if icon:
                            symbol = getattr(icon, "symbol", "")
                            logger.info(
                                "  Icon %d: symbol=%r",
                                idx,
                                symbol,
                            )
                    icon_str = " ".join(
                        convert_status_icon(getattr(i, "symbol", ""))
                        for i in icons
                        if i
                    )
                    icons_label.update(icon_str)
            except Exception:  # noqa: BLE001
                pass
