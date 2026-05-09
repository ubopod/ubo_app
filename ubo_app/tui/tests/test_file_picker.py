"""Tests for the FilePicker modal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_file_picker_typed_path_returns_path(tmp_path: Any) -> None:
    from textual.app import App

    from ubo_tui.views.file_picker import FilePicker

    real_file = tmp_path / "selected.bin"
    real_file.write_bytes(b"x")

    captured: dict[str, Any] = {}

    class _App(App[None]):
        async def on_mount(self) -> None:
            def _result(path: Path | None) -> None:
                captured["path"] = path
                self.exit()

            self.push_screen(
                FilePicker(initial_path=real_file, title="Pick"),
                _result,
            )

    async with _App().run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")  # ignored
        # Click Select via keyboard tab navigation: focus jumps from input
        # to the directory tree by default, so use the input's own submit.
        # Press Enter inside the input field to confirm the typed path.
        # First, ensure focus is on the input.
        try:
            input_widget = pilot.app.query_one("#picker-input")
            input_widget.focus()
        except Exception:  # noqa: BLE001
            pass
        await pilot.press("enter")
        await pilot.pause()

    assert captured["path"] == real_file


@pytest.mark.asyncio
async def test_file_picker_escape_returns_none(tmp_path: Any) -> None:
    from textual.app import App

    from ubo_tui.views.file_picker import FilePicker

    captured: dict[str, Any] = {"path": "untouched"}

    class _App(App[None]):
        async def on_mount(self) -> None:
            def _result(path: Path | None) -> None:
                captured["path"] = path
                self.exit()

            self.push_screen(
                FilePicker(initial_path=tmp_path, title="Pick"),
                _result,
            )

    async with _App().run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert captured["path"] is None


@pytest.mark.asyncio
async def test_file_picker_typed_missing_path_does_not_dismiss(
    tmp_path: Any,
) -> None:
    """Typing a non-existent path and pressing Enter should not dismiss."""
    from textual.app import App

    from ubo_tui.views.file_picker import FilePicker

    closed: dict[str, Any] = {"value": False}

    class _App(App[None]):
        async def on_mount(self) -> None:
            def _result(path: Path | None) -> None:
                closed["value"] = True
                closed["path"] = path
                self.exit()

            self.push_screen(
                FilePicker(
                    initial_path=tmp_path / "no-such-file.bin",
                    title="Pick",
                ),
                _result,
            )

    async with _App().run_test() as pilot:
        await pilot.pause()
        try:
            input_widget = pilot.app.query_one("#picker-input")
            input_widget.focus()
        except Exception:  # noqa: BLE001
            pass
        await pilot.press("enter")
        await pilot.pause()
        # Modal should still be open; cancel to clean up.
        await pilot.press("escape")
        await pilot.pause()

    # The first Enter should NOT have produced a real path; only the Escape
    # should have closed the picker (with None).
    assert closed["value"] is True
    assert closed["path"] is None
