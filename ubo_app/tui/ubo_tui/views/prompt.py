"""Prompt confirmation view."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal
from textual.widgets import Label

from ubo_tui.views.base import BaseView
from ubo_tui.views.menu import convert_icon

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class PromptView(BaseView):
    """Title + prompt body + horizontal button row."""

    DEFAULT_CSS = """
    PromptView {
        layout: vertical;
        padding: 2;
        align: center middle;
    }

    .prompt-title {
        text-align: center;
        text-style: bold;
        color: #87afff;
        margin-bottom: 1;
    }

    .prompt-body {
        text-align: center;
        margin-bottom: 1;
    }

    .prompt-icon {
        text-align: center;
        height: 3;
    }

    .prompt-buttons {
        height: auto;
        align-horizontal: center;
        margin-top: 1;
    }

    .prompt-button {
        height: 3;
        padding: 0 2;
        border: solid #666666;
        margin: 0 1;
    }

    .prompt-button.selected {
        border: solid green;
        background: #003300;
    }
    """

    def __init__(self, view_data: Any, **kwargs: Any) -> None:
        super().__init__(view_data, **kwargs)
        self._title: str = ""
        self._prompt: str = ""
        self._icon: str = ""
        self._items: list[Any] = []
        self._item_labels: list[str] = []
        self._selected_index: int = 0

        if view_data:
            self._title = getattr(view_data, "title", "") or ""
            self._prompt = getattr(view_data, "prompt", "") or ""
            self._icon = getattr(view_data, "icon", "") or ""

            items_container = getattr(view_data, "items", None)
            if items_container:
                self._items = list(getattr(items_container, "items", []))
                for raw_item in self._items:
                    item = raw_item
                    if hasattr(item, "items") and item.items is not None:
                        item = item.items
                    self._item_labels.append(getattr(item, "label", "") or "")

    @property
    def item_count(self) -> int:
        return len(self._items)

    def get_item_label(self, index: int) -> str | None:
        if 0 <= index < len(self._item_labels):
            return self._item_labels[index]
        return None

    def compose(self) -> ComposeResult:
        if self._icon:
            yield Label(self._icon, classes="prompt-icon")
        if self._title:
            yield Label(self._title, classes="prompt-title", markup=False)
        if self._prompt:
            yield Label(self._prompt, classes="prompt-body", markup=False)

        if self._items:
            with Horizontal(classes="prompt-buttons"):
                for i, raw_item in enumerate(self._items):
                    item = raw_item
                    if hasattr(item, "items") and item.items is not None:
                        item = item.items
                    raw_icon = getattr(item, "icon", "") or ""
                    label = getattr(item, "label", "") or ""
                    icon = convert_icon(raw_icon)
                    text = f"{icon} {label}".strip() if label else icon
                    classes = "prompt-button selected" if i == 0 else "prompt-button"
                    yield Label(
                        text,
                        classes=classes,
                        id=f"prompt-button-{i}",
                        markup=False,
                    )

    def update_selection(self, index: int) -> None:
        self._selected_index = index
        for i in range(len(self._items)):
            try:
                button = self.query_one(f"#prompt-button-{i}", Label)
                if i == index:
                    button.add_class("selected")
                else:
                    button.remove_class("selected")
            except Exception:  # noqa: BLE001
                pass
