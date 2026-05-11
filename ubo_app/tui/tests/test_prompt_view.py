"""Tests for the PromptView."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class _Item:
    label: str
    icon: str = ""


@dataclass
class _Items:
    items: list[_Item]


@dataclass
class _Prompt:
    title: str = "Confirm"
    prompt: str = "Are you sure?"
    icon: str = ""
    items: Any = None


@pytest.mark.asyncio
async def test_prompt_view_exposes_item_labels() -> None:
    from textual.app import App

    from ubo_tui.views.prompt import PromptView

    captured: dict[str, Any] = {}

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            data = _Prompt(items=_Items(items=[_Item(label="Yes"), _Item(label="No")]))
            view = PromptView(data, id="view")
            captured["view"] = view
            yield view

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test():
        pass

    view = captured["view"]
    expected_item_count = 2
    assert view.item_count == expected_item_count
    assert view.get_item_label(0) == "Yes"
    assert view.get_item_label(1) == "No"
    assert view.get_item_label(99) is None


@pytest.mark.asyncio
async def test_prompt_view_renders_title_and_prompt_text() -> None:
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.views.prompt import PromptView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            data = _Prompt(
                title="Reboot",
                prompt="Reboot now?",
                items=_Items(items=[_Item(label="OK")]),
            )
            yield PromptView(data, id="view")

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        rendered_labels = [
            label.render() for label in pilot.app.query(Label)
        ]

    rendered = " ".join(str(label) for label in rendered_labels)
    assert "Reboot" in rendered
    assert "Reboot now?" in rendered
    assert "OK" in rendered


@pytest.mark.asyncio
async def test_prompt_view_no_items_renders_zero_count() -> None:
    from textual.app import App

    from ubo_tui.views.prompt import PromptView

    captured: dict[str, Any] = {}

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            view = PromptView(_Prompt(items=None), id="view")
            captured["view"] = view
            yield view

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test():
        pass

    assert captured["view"].item_count == 0


@pytest.mark.asyncio
async def test_prompt_view_update_selection_marks_button() -> None:
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.views.prompt import PromptView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield PromptView(
                _Prompt(items=_Items(items=[_Item(label="A"), _Item(label="B")])),
                id="view",
            )

        async def on_mount(self) -> None:
            view = self.query_one("#view", PromptView)
            view.update_selection(1)
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        button_b = pilot.app.query_one("#prompt-button-1", Label)
        button_a = pilot.app.query_one("#prompt-button-0", Label)
        assert "selected" in button_b.classes
        assert "selected" not in button_a.classes
