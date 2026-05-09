"""Modal file picker built on Textual's DirectoryTree."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class FilePicker(ModalScreen[Path | None]):
    """Modal screen letting the user pick a local file path.

    The screen offers two ways to choose a file:

    - Type/paste a path into the top ``Input``.
    - Navigate the ``DirectoryTree`` and press Enter on a file.

    Pressing **Cancel** or *Escape* dismisses the modal with ``None``.
    """

    DEFAULT_CSS = """
    FilePicker {
        align: center middle;
    }

    FilePicker > Vertical {
        background: #15151f;
        border: round #5f87ff;
        width: 80%;
        height: 80%;
        padding: 1 2;
    }

    FilePicker .picker-title {
        text-style: bold;
        color: #87afff;
        margin-bottom: 1;
    }

    FilePicker Input {
        margin-bottom: 1;
    }

    FilePicker DirectoryTree {
        height: 1fr;
        border: solid #444466;
    }

    FilePicker .picker-buttons {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }

    FilePicker .picker-buttons Button {
        margin-left: 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        initial_path: Path | None = None,
        *,
        title: str = "Select a file",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        # Resolve start directory: if initial_path is a file, use its parent.
        if initial_path is None:
            start = Path.home()
        else:
            start = initial_path if initial_path.is_dir() else initial_path.parent
            if not start.exists():
                start = Path.home()
        self._start_dir = start
        self._initial_value = str(initial_path) if initial_path else ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title, classes="picker-title", markup=False)
            yield Input(
                value=self._initial_value,
                placeholder="Type a path or browse below",
                id="picker-input",
            )
            yield DirectoryTree(str(self._start_dir), id="picker-tree")
            with Horizontal(classes="picker-buttons"):
                yield Button("Cancel", id="picker-cancel")
                yield Button("Select", id="picker-confirm", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-cancel":
            self.action_cancel()
        elif event.button.id == "picker-confirm":
            self._confirm_typed_path()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "picker-input":
            self._confirm_typed_path()

    def on_directory_tree_file_selected(
        self,
        event: DirectoryTree.FileSelected,
    ) -> None:
        path = Path(str(event.path))
        logger.info("FilePicker: tree selected %s", path)
        self.dismiss(path)

    def _confirm_typed_path(self) -> None:
        try:
            input_widget = self.query_one("#picker-input", Input)
        except Exception:  # noqa: BLE001
            self.dismiss(None)
            return
        text = (input_widget.value or "").strip()
        if not text:
            self.app.notify("Please enter a path or pick a file", severity="warning")
            return
        path = Path(text).expanduser()
        if not path.exists():
            self.app.notify(f"Path does not exist: {path}", severity="error")
            return
        if not path.is_file():
            self.app.notify(f"Not a regular file: {path}", severity="error")
            return
        self.dismiss(path)

    def action_cancel(self) -> None:
        self.dismiss(None)
