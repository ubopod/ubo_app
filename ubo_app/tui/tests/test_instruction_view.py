"""Tests for the InstructionView."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class _Instruction:
    title: str = "Updating"
    instruction: str = "Please wait..."
    icon: str = ""
    spinner: bool = False
    progress_text: str = ""
    footer_text: str = ""


@pytest.mark.asyncio
async def test_instruction_view_with_spinner_mounts_loading_indicator() -> None:
    from textual.app import App
    from textual.widgets import LoadingIndicator

    from ubo_tui.views.instruction import InstructionView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield InstructionView(_Instruction(spinner=True), id="view")

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        indicators = list(pilot.app.query(LoadingIndicator))
        assert len(indicators) == 1


@pytest.mark.asyncio
async def test_instruction_view_without_spinner_has_no_loading_indicator() -> None:
    from textual.app import App
    from textual.widgets import LoadingIndicator

    from ubo_tui.views.instruction import InstructionView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield InstructionView(_Instruction(spinner=False), id="view")

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        assert list(pilot.app.query(LoadingIndicator)) == []


@pytest.mark.asyncio
async def test_instruction_view_renders_title_and_progress_and_footer() -> None:
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.views.instruction import InstructionView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield InstructionView(
                _Instruction(
                    title="Updating",
                    instruction="Please wait...",
                    progress_text="50%",
                    footer_text="Do not power off",
                ),
                id="view",
            )

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        rendered = " ".join(
            str(label.render()) for label in pilot.app.query(Label)
        )

    assert "Updating" in rendered
    assert "Please wait" in rendered
    assert "50%" in rendered
    assert "Do not power off" in rendered


@pytest.mark.asyncio
async def test_instruction_view_item_count_is_zero() -> None:
    from textual.app import App

    from ubo_tui.views.instruction import InstructionView

    captured: dict[str, Any] = {}

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            view = InstructionView(_Instruction(), id="view")
            captured["view"] = view
            yield view

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test():
        pass

    assert captured["view"].item_count == 0
