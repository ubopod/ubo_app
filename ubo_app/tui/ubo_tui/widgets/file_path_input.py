"""Composite widget: text Input + Browse button + F2 keybinding."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, Input

from ubo_tui.views.file_picker import FilePicker

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class FilePathInput(Widget):
    """Single-line file path input with a Browse button.

    Pressing **F2** while focused (or clicking Browse) opens a ``FilePicker``
    modal. The selected path is written into the embedded ``Input``.
    """

    DEFAULT_CSS = """
    FilePathInput {
        height: auto;
    }

    FilePathInput Horizontal {
        height: auto;
    }

    FilePathInput Input {
        width: 1fr;
    }

    FilePathInput Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("f2", "browse", "Browse", show=True),
    ]

    can_focus = True

    def __init__(
        self,
        value: str = "",
        *,
        placeholder: str = "Type a path or press F2 to browse",
        title: str = "Select a file",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._initial_value = value
        self._placeholder = placeholder
        self._picker_title = title

    @property
    def value(self) -> str:
        try:
            return self.query_one(".file-path-text", Input).value
        except Exception:  # noqa: BLE001
            return self._initial_value

    @value.setter
    def value(self, new_value: str) -> None:
        try:
            self.query_one(".file-path-text", Input).value = new_value
        except Exception:  # noqa: BLE001
            self._initial_value = new_value

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(
                value=self._initial_value,
                placeholder=self._placeholder,
                classes="file-path-text",
            )
            yield Button("Browse", classes="file-path-browse")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if "file-path-browse" in event.button.classes:
            self.action_browse()
            event.stop()

    def action_browse(self) -> None:
        """Open the FilePicker modal and write the result back into the input."""
        current = self.value
        initial = Path(current).expanduser() if current else None

        def _set_value(path: Path | None) -> None:
            if path is not None:
                self.value = str(path)

        self.app.push_screen(
            FilePicker(initial_path=initial, title=self._picker_title),
            _set_value,
        )

    def get_path(self) -> Path | None:
        """Return the current value as a Path, or None if empty/missing."""
        text = (self.value or "").strip()
        if not text:
            return None
        return Path(text).expanduser()
