"""Instruction view (single-step guidance with optional spinner)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.widgets import Label, LoadingIndicator

from ubo_tui.views.base import BaseView

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class InstructionView(BaseView):
    """Title + optional spinner + instruction text + progress/footer."""

    DEFAULT_CSS = """
    InstructionView {
        layout: vertical;
        padding: 2;
        align: center middle;
    }

    .instruction-title {
        text-align: center;
        text-style: bold;
        color: #87afff;
        margin-bottom: 1;
    }

    .instruction-icon {
        text-align: center;
        height: 3;
    }

    .instruction-body {
        text-align: center;
        margin-bottom: 1;
    }

    .instruction-progress {
        text-align: center;
        color: #cccccc;
        margin-top: 1;
    }

    .instruction-footer {
        text-align: center;
        color: #888888;
        margin-top: 1;
    }
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._title: str = ""
        self._instruction: str = ""
        self._icon: str = ""
        self._spinner: bool = False
        self._progress_text: str = ""
        self._footer_text: str = ""

        if view_data:
            self._title = getattr(view_data, "title", "") or ""
            self._instruction = getattr(view_data, "instruction", "") or ""
            self._icon = getattr(view_data, "icon", "") or ""
            self._spinner = bool(getattr(view_data, "spinner", False))
            self._progress_text = getattr(view_data, "progress_text", "") or ""
            self._footer_text = getattr(view_data, "footer_text", "") or ""

    @property
    def item_count(self) -> int:
        # Instructions are non-interactive.
        return 0

    def compose(self) -> ComposeResult:
        if self._icon:
            yield Label(self._icon, classes="instruction-icon")
        if self._title:
            yield Label(self._title, classes="instruction-title", markup=False)
        if self._spinner:
            yield LoadingIndicator()
        if self._instruction:
            yield Label(self._instruction, classes="instruction-body", markup=False)
        if self._progress_text:
            yield Label(
                self._progress_text,
                classes="instruction-progress",
                markup=False,
            )
        if self._footer_text:
            yield Label(
                self._footer_text,
                classes="instruction-footer",
                markup=False,
            )
