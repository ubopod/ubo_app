"""Top-level RenderView that dispatches on RenderViewData.kind."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from ubo_tui.views.base import BaseView
from ubo_tui.views.render_kinds.props import (
    _list_items,
    _props_map,
    prop_string,
    prop_string_list,
)
from ubo_tui.views.render_kinds.qr import render_qr_text

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


def _prop_string_rows(view_data: Any, key: str) -> list[str]:
    """Like ``prop_string_list``, but keeps blanks.

    ``labels``/``values``/``units`` are parallel arrays; dropping an empty
    string (a unit-less AQI) would shift every unit below it onto the wrong
    row.
    """
    entry = _props_map(view_data).get(key)
    rows: list[str] = []
    for item in _list_items(entry):
        value = getattr(item, "string", None)
        rows.append(value if isinstance(value, str) else "")
    return rows


class RenderView(BaseView):
    """Renders RenderViewData by switching on its ``kind`` field."""

    DEFAULT_CSS = """
    RenderView {
        layout: vertical;
        padding: 1;
    }

    RenderView .render-title {
        text-align: center;
        text-style: bold;
        color: #87afff;
        margin-bottom: 1;
    }

    RenderView .render-status {
        text-align: center;
        margin: 1;
    }

    RenderView .render-text {
        padding: 1;
    }

    RenderView .render-qr {
        text-align: center;
    }

    RenderView .render-label {
        text-align: center;
        margin-top: 1;
        color: #cccccc;
    }

    RenderView .render-fallback {
        text-align: center;
        color: #888888;
        margin-top: 1;
    }
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._title: str = ""
        self._kind: str = ""
        if view_data:
            self._title = getattr(view_data, "title", "") or ""
            self._kind = getattr(view_data, "kind", "") or ""

    @property
    def item_count(self) -> int:
        # RenderView is non-interactive (Phase 2 scope).
        return 0

    def compose(self) -> ComposeResult:
        if self._title:
            yield Label(self._title, classes="render-title", markup=False)

        kind = self._kind
        if kind == "qr_code":
            yield from self._compose_qr_code()
        elif kind == "qr_code_carousel":
            yield from self._compose_qr_carousel()
        elif kind == "readings":
            yield from self._compose_readings()
        elif kind == "status":
            yield from self._compose_status()
        elif kind == "text_viewer":
            yield from self._compose_text_viewer()
        elif kind in {"image_viewer", "frame_stream"}:
            yield from self._compose_unsupported(kind)
        else:
            # Fallback: try to render a "text" prop if any.
            yield from self._compose_text_viewer()

    # --- per-kind composers -------------------------------------------------

    def _compose_qr_code(self) -> ComposeResult:
        value = prop_string(self.view_data, "value")
        label = prop_string(self.view_data, "label") or value
        rendered = render_qr_text(value)
        yield Static(rendered, classes="render-qr")
        if label:
            yield Label(label, classes="render-label", markup=False)

    def _compose_qr_carousel(self) -> ComposeResult:
        values = prop_string_list(self.view_data, "values")
        labels = prop_string_list(self.view_data, "labels")
        if not values:
            yield Label("(no QR codes provided)", classes="render-fallback")
            return
        # Phase 2 renders only the first item; navigation between codes
        # would require keybindings + state which is out of scope here.
        value = values[0]
        label = labels[0] if labels else value
        rendered = render_qr_text(value)
        yield Static(rendered, classes="render-qr")
        if label:
            yield Label(label, classes="render-label", markup=False)
        if len(values) > 1:
            yield Label(
                f"(showing 1 of {len(values)})",
                classes="render-fallback",
                markup=False,
            )

    def _compose_readings(self) -> ComposeResult:
        labels = _prop_string_rows(self.view_data, "labels")
        values = _prop_string_rows(self.view_data, "values")
        units = _prop_string_rows(self.view_data, "units")
        if not labels:
            placeholder = (
                prop_string(self.view_data, "placeholder") or "No readings yet"
            )
            yield Label(placeholder, classes="render-fallback", markup=False)
            return
        name_width = max(len(label) for label in labels)
        with VerticalScroll(classes="render-text"):
            for index, label in enumerate(labels):
                value = values[index] if index < len(values) else "—"
                unit = units[index] if index < len(units) else ""
                reading = f"{value} {unit}".strip()
                yield Static(f"{label:<{name_width}}  {reading}", markup=False)

    def _compose_status(self) -> ComposeResult:
        text = prop_string(self.view_data, "text") or "(no status text)"
        yield Label(text, classes="render-status", markup=False)

    def _compose_text_viewer(self) -> ComposeResult:
        text = prop_string(self.view_data, "text")
        with VerticalScroll(classes="render-text"):
            if text:
                yield Static(text)
            else:
                yield Label("(no text content)", classes="render-fallback")

    def _compose_unsupported(self, kind: str) -> ComposeResult:
        yield Label(
            f"({kind} preview unavailable in TUI; use the WebUI)",
            classes="render-fallback",
            markup=False,
        )
