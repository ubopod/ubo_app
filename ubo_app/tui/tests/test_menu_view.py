"""Tests for the MenuView title position indicator and item handling."""

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
class _Menu:
    title: str = "Apps"
    heading: str | None = None
    sub_heading: str | None = None
    items: Any = None


APPS_MENU_ITEMS = (
    "Add New App",
    "Home Automation",
    "Networking",
    "AI Agents",
    "AI Engines",
    "Remote Access",
    "Files",
    "Container Management",
    "Other",
)
APPS_MENU_ITEM_COUNT = len(APPS_MENU_ITEMS)


def _make_apps_menu() -> _Menu:
    """9-item menu mimicking the real Apps menu (last item = 'Other')."""
    return _Menu(
        title="Apps",
        items=_Items(items=[_Item(label=label) for label in APPS_MENU_ITEMS]),
    )


@pytest.mark.asyncio
async def test_menu_title_shows_position_for_paginated_menu() -> None:
    """A 9-item menu should show '[1/9]' in the title initially."""
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.views.menu import MenuView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield MenuView(_make_apps_menu(), id="view")

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        title = pilot.app.query_one("#menu-title", Label)
        rendered = str(title.render())

    assert "Apps" in rendered
    assert "[1/9]" in rendered


@pytest.mark.asyncio
async def test_menu_title_updates_when_selection_changes() -> None:
    """update_selection() should update the title position to reflect index."""
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.views.menu import MenuView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield MenuView(_make_apps_menu(), id="view")

        async def on_mount(self) -> None:
            view = self.query_one("#view", MenuView)
            view.update_selection(8)  # last item ("Other")
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        title = pilot.app.query_one("#menu-title", Label)
        rendered = str(title.render())

    assert "[9/9]" in rendered


@pytest.mark.asyncio
async def test_menu_title_omits_position_for_short_menu() -> None:
    """Single-item menu should not show '[1/1]' to keep the title clean."""
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.views.menu import MenuView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield MenuView(
                _Menu(title="Solo", items=_Items(items=[_Item(label="Only")])),
                id="view",
            )

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        title = pilot.app.query_one("#menu-title", Label)
        rendered = str(title.render())

    assert "[" not in rendered
    assert "Solo" in rendered


@pytest.mark.asyncio
async def test_menu_view_keeps_all_items_no_truncation() -> None:
    """Regression guard: all 9 items must be available on the view."""
    from textual.app import App

    from ubo_tui.views.menu import MenuView

    captured: dict[str, Any] = {}

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            view = MenuView(_make_apps_menu(), id="view")
            captured["view"] = view
            yield view

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test():
        pass

    view = captured["view"]
    assert view.item_count == APPS_MENU_ITEM_COUNT
    assert view.get_item_label(0) == APPS_MENU_ITEMS[0]
    assert view.get_item_label(APPS_MENU_ITEM_COUNT - 1) == APPS_MENU_ITEMS[-1]
