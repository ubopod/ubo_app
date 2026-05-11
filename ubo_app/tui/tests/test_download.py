"""Tests for the TUI download flow (HTTP client + modal).

The TUI downloads files via the WebUI's existing ``/download/<token>`` HTTP
endpoint rather than a separate gRPC stream, so these tests spin up a small
``http.server`` on a free local port to act as the WebUI.
"""

from __future__ import annotations

import http.server
import socket
import threading
from typing import TYPE_CHECKING, Any, Self

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _DownloadServer:
    """Minimal HTTP server that maps /download/<token> -> bytes payload."""

    def __init__(self, payloads: dict[str, tuple[str, bytes]]) -> None:
        self._payloads = payloads
        self.port = _free_port()

        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if not self.path.startswith("/download/"):
                    self.send_error(404)
                    return
                token = self.path[len("/download/"):]
                payload = outer._payloads.get(token)  # noqa: SLF001
                if payload is None:
                    self.send_error(404, "Unknown token")
                    return
                filename, data = payload
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{filename}"',
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_: Any, **__: Any) -> None:
                # Silence noisy stderr during tests.
                pass

        self._server = http.server.HTTPServer(("127.0.0.1", self.port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


def _make_client(web_port: int) -> Any:
    from ubo_tui.client import TUIClient

    return TUIClient("127.0.0.1", 50051, web_port=web_port)


@pytest.mark.asyncio
async def test_download_writes_concatenated_chunks(tmp_path: Path) -> None:
    payload = b"hello world" * 100
    with _DownloadServer({"tok-1": ("greeting.txt", payload)}) as server:
        client = _make_client(server.port)
        target = tmp_path / "out.txt"
        filename, written = await client.download_file("tok-1", target)

    assert filename == "greeting.txt"
    assert written == len(payload)
    assert target.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_creates_parent_directory(tmp_path: Path) -> None:
    with _DownloadServer({"tok-2": ("a.bin", b"x")}) as server:
        client = _make_client(server.port)
        target = tmp_path / "nested" / "subdir" / "a.bin"
        filename, written = await client.download_file("tok-2", target)

    assert filename == "a.bin"
    assert written == 1
    assert target.read_bytes() == b"x"


@pytest.mark.asyncio
async def test_download_falls_back_to_target_name_when_no_disposition(
    tmp_path: Path,
) -> None:
    """When the server omits Content-Disposition, we use target_path.name."""

    class _NoDispositionServer:
        def __init__(self) -> None:
            self.port = _free_port()

            class _H(http.server.BaseHTTPRequestHandler):
                def do_GET(self) -> None:
                    self.send_response(200)
                    self.send_header("Content-Length", "3")
                    self.end_headers()
                    self.wfile.write(b"abc")

                def log_message(self, *_: Any, **__: Any) -> None:
                    pass

            self._server = http.server.HTTPServer(("127.0.0.1", self.port), _H)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
            )

        def __enter__(self) -> Any:
            self._thread.start()
            return self

        def __exit__(self, *_: object) -> None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=2)

    with _NoDispositionServer() as server:
        client = _make_client(server.port)
        target = tmp_path / "fallback.bin"
        filename, written = await client.download_file("tok", target)

    assert filename == "fallback.bin"
    assert written == len(b"abc")


@pytest.mark.asyncio
async def test_download_unknown_token_raises(tmp_path: Path) -> None:
    with _DownloadServer({"good": ("data.bin", b"x")}) as server:
        client = _make_client(server.port)
        with pytest.raises(RuntimeError, match="HTTP 404"):
            await client.download_file("bad-token", tmp_path / "out.bin")


@pytest.mark.asyncio
async def test_download_unreachable_host_raises(tmp_path: Path) -> None:
    """Connection failures should bubble up as RuntimeError."""
    from ubo_tui.client import TUIClient

    # Port 1 is reserved and unbound — connect should fail fast.
    client = TUIClient("127.0.0.1", 50051, web_port=1)
    with pytest.raises(RuntimeError, match="Could not reach"):
        await client.download_file("tok", tmp_path / "out.bin")


@pytest.mark.asyncio
async def test_download_modal_save_button_streams_file(tmp_path: Path) -> None:
    """Pressing Save should HTTP-GET the file and write it to disk."""
    from textual.app import App

    from ubo_tui.views.download_modal import DownloadModal

    target = tmp_path / "Downloads" / "report.txt"
    payload = b"report-bytes"

    with _DownloadServer({"tok-modal": ("report.txt", payload)}) as server:
        client = _make_client(server.port)

        class _App(App[None]):
            async def on_mount(self) -> None:
                self.push_screen(
                    DownloadModal(
                        client,
                        "tok-modal",
                        "report.txt",
                        default_dir=target.parent,
                    ),
                )

        async with _App().run_test() as pilot:
            await pilot.pause()
            from textual.widgets import Button

            save_btn = pilot.app.screen.query_one("#download-save", Button)
            save_btn.press()
            for _ in range(20):
                if target.exists():
                    break
                await pilot.pause()

    assert target.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_modal_cancel_dismisses_without_download(
    tmp_path: Path,
) -> None:
    from textual.app import App

    from ubo_tui.views.download_modal import DownloadModal

    target_dir = tmp_path / "Downloads"
    closed: dict[str, bool] = {"value": False}

    with _DownloadServer({"tok-cancel": ("never.txt", b"unused")}) as server:
        client = _make_client(server.port)

        class _App(App[None]):
            async def on_mount(self) -> None:
                def _result(_: Any) -> None:
                    closed["value"] = True
                    self.exit()

                self.push_screen(
                    DownloadModal(
                        client,
                        "tok-cancel",
                        "never.txt",
                        default_dir=target_dir,
                    ),
                    _result,
                )

        async with _App().run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    assert closed["value"] is True
    assert not target_dir.exists()
