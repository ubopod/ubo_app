"""Tests for the status-bar progress rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class _ProgressNotification:
    id: str = "n"
    progress: float | None = None
    color: str = ""


@dataclass
class _ProgressContainer:
    items: list[_ProgressNotification]


@dataclass
class _IconsContainer:
    items: list[Any] = field(default_factory=list)


@dataclass
class _StatusBarData:
    clock: str | None = None
    temperature: float | None = None
    is_recording: bool = False
    is_replaying: bool = False
    is_recording_audio: bool = False
    progress_notifications: _ProgressContainer | None = None
    icons: _IconsContainer | None = None


# ---- _render_progress_bar (unit) -------------------------------------------


def test_render_progress_bar_determinate_half() -> None:
    from ubo_tui.widgets.status_bar import _render_progress_bar

    rendered = _render_progress_bar(0.5)
    assert "█" * 5 in rendered
    assert "░" * 5 in rendered
    assert "50%" in rendered


def test_render_progress_bar_determinate_zero() -> None:
    from ubo_tui.widgets.status_bar import _render_progress_bar

    rendered = _render_progress_bar(0.0)
    # All empty cells, plus 0%.
    assert "░" * 10 in rendered
    assert "0%" in rendered


def test_render_progress_bar_determinate_full() -> None:
    from ubo_tui.widgets.status_bar import _render_progress_bar

    rendered = _render_progress_bar(1.0)
    assert "█" * 10 in rendered
    assert "100%" in rendered


def test_render_progress_bar_clamps_out_of_range() -> None:
    from ubo_tui.widgets.status_bar import _render_progress_bar

    over = _render_progress_bar(1.5)
    under = _render_progress_bar(-0.2)
    assert "100%" in over
    assert "0%" in under


def test_render_progress_bar_indeterminate_no_percent() -> None:
    from ubo_tui.widgets.status_bar import _render_progress_bar

    rendered = _render_progress_bar(None)
    assert "%" not in rendered
    # 10 indeterminate dots between brackets.
    assert "·" * 10 in rendered


def test_render_progress_bar_nan_treated_as_indeterminate() -> None:
    from ubo_tui.widgets.status_bar import _render_progress_bar

    rendered = _render_progress_bar(float("nan"))
    assert "%" not in rendered
    assert "·" in rendered


# ---- _render_progress_label (unit, list semantics) -------------------------


def test_render_progress_label_empty_list_is_blank() -> None:
    from ubo_tui.widgets.status_bar import _render_progress_label

    assert _render_progress_label([]) == ""


def test_render_progress_label_single_entry() -> None:
    from ubo_tui.widgets.status_bar import _render_progress_label

    label = _render_progress_label([_ProgressNotification(progress=0.5)])
    assert "50%" in label
    assert "more" not in label


def test_render_progress_label_multiple_entries_appends_more() -> None:
    from ubo_tui.widgets.status_bar import _render_progress_label

    items = [
        _ProgressNotification(progress=0.3),
        _ProgressNotification(progress=0.6),
        _ProgressNotification(progress=None),
    ]
    label = _render_progress_label(items)
    # First entry is 30% determinate; the 2 extras get summarized.
    assert "30%" in label
    assert "(+2 more)" in label


# ---- FooterBar integration -------------------------------------------------


@pytest.mark.asyncio
async def test_footer_bar_renders_progress_when_data_includes_it() -> None:
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.widgets.status_bar import FooterBar

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield FooterBar(id="footer")

        async def on_mount(self) -> None:
            footer = self.query_one("#footer", FooterBar)
            footer.update_data(
                _StatusBarData(
                    clock="12:34",
                    temperature=42.5,
                    progress_notifications=_ProgressContainer(
                        items=[_ProgressNotification(progress=0.7)],
                    ),
                ),
            )
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        progress_label = pilot.app.query_one("#footer-progress", Label)
        rendered = str(progress_label.render())

    assert "70%" in rendered
    assert "█" in rendered


@pytest.mark.asyncio
async def test_footer_bar_clears_progress_when_no_notifications() -> None:
    """After progress disappears, the label should be blank again."""
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.widgets.status_bar import FooterBar

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield FooterBar(id="footer")

        async def on_mount(self) -> None:
            footer = self.query_one("#footer", FooterBar)
            footer.update_data(
                _StatusBarData(
                    progress_notifications=_ProgressContainer(
                        items=[_ProgressNotification(progress=0.4)],
                    ),
                ),
            )
            footer.update_data(
                _StatusBarData(
                    progress_notifications=_ProgressContainer(items=[]),
                ),
            )
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        progress_label = pilot.app.query_one("#footer-progress", Label)
        rendered = str(progress_label.render())

    assert rendered == ""
