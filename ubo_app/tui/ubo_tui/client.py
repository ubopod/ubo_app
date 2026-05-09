"""gRPC client wrapper for TUI-specific operations."""

from __future__ import annotations

import asyncio
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# WebUI HTTP listen port. Mirrors UBO_WEB_UI_LISTEN_PORT default in
# ubo_app/constants/__init__.py.
DEFAULT_WEB_UI_PORT = 4321

# Bytes per read when streaming an HTTP download to disk.
HTTP_DOWNLOAD_CHUNK_SIZE = 64 * 1024

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ubo_bindings.ubo.v1 import StatusBarData, ViewData


def _filename_from_content_disposition(header: str) -> str:
    """Best-effort filename extraction from a Content-Disposition header."""
    if not header:
        return ""
    # Look for filename="..." or filename=... — minimal parser is fine here.
    parts = [p.strip() for p in header.split(";")]
    for part in parts:
        if part.lower().startswith("filename="):
            value = part.split("=", 1)[1].strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            return value
    return ""


class TUIClient:
    """Client for TUI to communicate with ubo_app via gRPC."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 50051,
        web_port: int = DEFAULT_WEB_UI_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self.web_port = web_port
        self._client = None
        self._unsubscribe_view: Callable[[], None] | None = None

    def connect(self) -> None:
        """Establish gRPC connection."""
        from ubo_bindings.client import UboRPCClient

        self._client = UboRPCClient(self.host, self.port)

    def disconnect(self) -> None:
        """Close gRPC connection."""
        if self._unsubscribe_view:
            self._unsubscribe_view()
        if self._client:
            self._client.close()

    def subscribe_view_changes(
        self,
        callback: Callable[[ViewData, StatusBarData | None], None],
    ) -> Callable[[], None]:
        """Subscribe to view and status bar state changes using autorun.

        This uses autorun to get immediate initial state and updates on changes,
        instead of subscribe_event which only fires on new events.
        """
        if not self._client:
            msg = "Client not connected"
            raise RuntimeError(msg)

        # Use autorun to subscribe to state changes
        # This gives us the initial state immediately plus updates
        @self._client.autorun(
            [
                "state.main.current_view",
                "state.main.status_bar",
            ],
        )
        def handler(results: list) -> None:
            logger.info("autorun handler called with %d results", len(results))
            current_view = results[0] if len(results) > 0 else None
            status_bar = results[1] if len(results) > 1 else None
            logger.info(
                "current_view=%s, status_bar=%s",
                type(current_view).__name__ if current_view else None,
                type(status_bar).__name__ if status_bar else None,
            )
            if current_view is not None:
                callback(current_view, status_bar)
            else:
                logger.warning("current_view is None, skipping callback")

        self._unsubscribe_view = handler
        return handler

    def select_item(self, index: int) -> None:
        """Select menu item by index (0-2 for visible items)."""
        from ubo_bindings.ubo.v1 import Action, MenuChooseByIndexAction

        if self._client:
            action = Action(
                menu_choose_by_index_action=MenuChooseByIndexAction(index=index),
            )
            self._client.dispatch(action=action)

    def select_by_label(self, label: str) -> None:
        """Select menu item by label."""
        from ubo_bindings.ubo.v1 import Action, MenuChooseByLabelAction

        logger.info("select_by_label: dispatching label=%r", label)
        if self._client:
            action = Action(
                menu_choose_by_label_action=MenuChooseByLabelAction(label=label),
            )
            self._client.dispatch(action=action)
            logger.info("select_by_label: dispatch completed")

    def scroll(self, direction: str) -> None:
        """Scroll menu up or down."""
        from ubo_bindings.ubo.v1 import Action, MenuScrollAction, MenuScrollDirection

        if self._client:
            dir_enum = (
                MenuScrollDirection.UP
                if direction == "up"
                else MenuScrollDirection.DOWN
            )
            action = Action(
                menu_scroll_action=MenuScrollAction(direction=dir_enum),
            )
            self._client.dispatch(action=action)

    def go_back(self) -> None:
        """Navigate back in menu hierarchy."""
        from ubo_bindings.ubo.v1 import Action, MenuGoBackAction

        if self._client:
            action = Action(menu_go_back_action=MenuGoBackAction())
            self._client.dispatch(action=action)

    def go_home(self) -> None:
        """Return to home screen."""
        from ubo_bindings.ubo.v1 import Action, MenuGoHomeAction

        if self._client:
            action = Action(menu_go_home_action=MenuGoHomeAction())
            self._client.dispatch(action=action)

    def change_volume(self, amount: float) -> None:
        """Change playback volume by amount (-1.0 to 1.0)."""
        from ubo_bindings.ubo.v1 import Action, AudioChangeVolumeAction, AudioDevice

        if self._client:
            action = Action(
                audio_change_volume_action=AudioChangeVolumeAction(
                    amount=amount,
                    device=AudioDevice.OUTPUT,
                ),
            )
            self._client.dispatch(action=action)

    def execute_action(
        self,
        action_id: str,
        menu_key: str | None = None,
    ) -> None:
        """Execute a menu action by its action_id.

        This dispatches ExecuteMenuActionAction with the given action_id.

        Args:
            action_id: The action_id to execute.
            menu_key: Optional menu key to push if the handler returns a result.
        """
        from ubo_bindings.ubo.v1 import Action, ExecuteMenuActionAction

        if not self._client:
            return

        logger.info("execute_action: dispatching action_id=%s", action_id)
        action = Action(
            execute_menu_action_action=ExecuteMenuActionAction(
                action_id=action_id,
                menu_key=menu_key or "",
            ),
        )
        self._client.dispatch(action=action)

    def provide_input(
        self,
        input_id: str,
        value: str,
        data: dict[str, str],
        files: dict[str, bytes] | None = None,
    ) -> None:
        """Resolve an input demand with user-provided values."""
        from ubo_bindings.ubo.v1 import (
            Action,
            InputMethod,
            InputProvideAction,
            InputResult,
        )

        if not self._client:
            return

        logger.info("provide_input: id=%s, fields=%s", input_id, list(data.keys()))
        action = Action(
            input_provide_action=InputProvideAction(
                id=input_id,
                value=value,
                result=InputResult(
                    data=data,
                    files=files or {},
                    method=InputMethod.WEB_DASHBOARD,
                ),
            ),
        )
        self._client.dispatch(action=action)

    def cancel_input(self, input_id: str) -> None:
        """Cancel an input demand."""
        from ubo_bindings.ubo.v1 import Action, InputCancelAction

        if not self._client:
            return

        logger.info("cancel_input: id=%s", input_id)
        action = Action(input_cancel_action=InputCancelAction(id=input_id))
        self._client.dispatch(action=action)

    def upload_file_start(
        self,
        *,
        upload_id: str,
        filename: str,
        total_size: int,
        total_chunks: int,
        chunk_size: int,
        target_directory: str | None = None,
    ) -> None:
        """Begin a chunked file upload."""
        from ubo_bindings.ubo.v1 import Action, FileUploadStartAction

        if not self._client:
            return

        action = Action(
            file_upload_start_action=FileUploadStartAction(
                upload_id=upload_id,
                filename=filename,
                total_size=total_size,
                total_chunks=total_chunks,
                chunk_size=chunk_size,
                target_directory=target_directory,
            ),
        )
        self._client.dispatch(action=action)

    def upload_file_chunk(
        self,
        *,
        upload_id: str,
        chunk_index: int,
        data: bytes,
    ) -> None:
        """Send a single chunk of a file upload."""
        from ubo_bindings.ubo.v1 import Action, FileUploadChunkAction

        if not self._client:
            return

        action = Action(
            file_upload_chunk_action=FileUploadChunkAction(
                upload_id=upload_id,
                chunk_index=chunk_index,
                data=data,
            ),
        )
        self._client.dispatch(action=action)

    def upload_file_complete(self, *, upload_id: str) -> None:
        """Mark a chunked file upload as complete."""
        from ubo_bindings.ubo.v1 import Action, FileUploadCompleteAction

        if not self._client:
            return

        action = Action(
            file_upload_complete_action=FileUploadCompleteAction(
                upload_id=upload_id,
            ),
        )
        self._client.dispatch(action=action)

    async def download_file(
        self,
        download_token: str,
        target_path: Path,
    ) -> tuple[str, int]:
        """Stream a server-side download to ``target_path`` over HTTP.

        Reuses the WebUI's ``/download/<token>`` endpoint (the same one the
        browser uses) so the TUI doesn't need a separate transfer protocol.
        Runs the blocking ``urllib`` calls in a thread so the Textual event
        loop stays responsive.

        Returns ``(filename, bytes_written)`` derived from the
        ``Content-Disposition`` header (falling back to ``target_path.name``).
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        url = self._download_url(download_token)
        logger.info(
            "download_file: GET %s -> %s",
            url,
            target_path,
        )
        return await asyncio.to_thread(
            self._http_download_to_path,
            url,
            target_path,
        )

    def _download_url(self, download_token: str) -> str:
        token = urllib.parse.quote(download_token, safe="")
        return f"http://{self.host}:{self.web_port}/download/{token}"

    @staticmethod
    def _http_download_to_path(url: str, target_path: Path) -> tuple[str, int]:
        bytes_written = 0
        try:
            with urllib.request.urlopen(url) as response:  # noqa: S310
                filename = _filename_from_content_disposition(
                    response.headers.get("Content-Disposition", ""),
                ) or target_path.name
                with target_path.open("wb") as fh:
                    while True:
                        chunk = response.read(HTTP_DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        fh.write(chunk)
                        bytes_written += len(chunk)
        except urllib.error.HTTPError as exc:
            msg = f"HTTP {exc.code} from {url}: {exc.reason}"
            raise RuntimeError(msg) from exc
        except urllib.error.URLError as exc:
            msg = f"Could not reach {url}: {exc.reason}"
            raise RuntimeError(msg) from exc

        logger.info(
            "download_file: complete bytes=%d filename=%r",
            bytes_written,
            filename,
        )
        return filename, bytes_written
