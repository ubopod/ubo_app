"""Modal that asks the user where to save an incoming download."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from ubo_tui.widgets.file_path_input import FilePathInput

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from ubo_tui.client import TUIClient

logger = logging.getLogger(__name__)


class DownloadModal(ModalScreen[None]):
    """Prompt for a save path and stream the file from the device.

    Receives ``download_token`` and ``filename`` from a
    ``FileDownloadReadyEvent``. Default save path is ``~/Downloads/<filename>``.
    Pressing **Save** streams the file via ``client.download_file``; pressing
    **Cancel** or *Escape* dismisses without downloading.
    """

    DEFAULT_CSS = """
    DownloadModal {
        align: center middle;
    }

    DownloadModal > Vertical {
        background: #15151f;
        border: round #5f87ff;
        width: 80%;
        max-width: 90;
        height: auto;
        padding: 1 2;
    }

    DownloadModal .download-title {
        text-style: bold;
        color: #87afff;
        margin-bottom: 1;
    }

    DownloadModal .download-detail {
        margin-bottom: 1;
    }

    DownloadModal .download-status {
        margin-top: 1;
        color: #cccccc;
    }

    DownloadModal .download-buttons {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }

    DownloadModal .download-buttons Button {
        margin-left: 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        client: TUIClient,
        download_token: str,
        filename: str,
        *,
        default_dir: Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._client = client
        self._token = download_token
        self._filename = filename
        self._default_dir = default_dir or (Path.home() / "Downloads")
        self._in_progress = False

    def compose(self) -> ComposeResult:
        default_path = str(self._default_dir / self._filename)
        with Vertical():
            yield Label(
                "Download ready",
                classes="download-title",
                markup=False,
            )
            yield Label(
                f"File: {self._filename}",
                classes="download-detail",
                markup=False,
            )
            yield Label("Save to:", classes="download-detail", markup=False)
            yield FilePathInput(
                value=default_path,
                placeholder="Type a save path or press F2 to browse",
                title="Save downloaded file",
                id="download-path",
            )
            yield Label(
                "",
                classes="download-status",
                markup=False,
                id="download-status",
            )
            with Horizontal(classes="download-buttons"):
                yield Button("Cancel", id="download-cancel")
                yield Button("Save", id="download-save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "download-cancel":
            self.action_cancel()
        elif event.button.id == "download-save":
            self._start_download()

    def action_cancel(self) -> None:
        if self._in_progress:
            # Don't close mid-stream — let it finish or fail.
            self.app.notify(
                "Download in progress, please wait...",
                severity="warning",
            )
            return
        self.dismiss(None)

    def _start_download(self) -> None:
        if self._in_progress:
            return
        try:
            path_input = self.query_one("#download-path", FilePathInput)
        except Exception:  # noqa: BLE001
            self.app.notify("Path input missing", severity="error")
            return

        text = (path_input.value or "").strip()
        if not text:
            self.app.notify("Please enter a save path", severity="error")
            return

        target = Path(text).expanduser()
        if target.is_dir():
            target = target / self._filename

        self._in_progress = True
        self._set_status(f"Downloading to {target} ...")
        asyncio.create_task(self._run_download(target))

    async def _run_download(self, target: Path) -> None:
        try:
            filename, bytes_written = await self._client.download_file(
                self._token,
                target,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Download failed")
            self._in_progress = False
            self._set_status(f"Failed: {exc}")
            self.app.notify(f"Download failed: {exc}", severity="error")
            return

        self._in_progress = False
        self.app.notify(
            f"Saved {filename} ({bytes_written:,} bytes) to {target}",
            severity="information",
        )
        self.dismiss(None)

    def _set_status(self, message: str) -> None:
        try:
            label = self.query_one("#download-status", Label)
            label.update(message)
        except Exception:  # noqa: BLE001
            pass
