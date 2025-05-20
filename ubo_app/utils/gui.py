"""Provides reusable gui stuff."""

from __future__ import annotations

import pathlib
from typing import Literal, TypeAlias

from kivy.lang.builder import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from ubo_gui.page import PageWidget
from ubo_gui.prompt import PromptWidget

from ubo_app.colors import SUCCESS_COLOR

ItemParameters: TypeAlias = dict[Literal['background_color', 'color', 'icon'], str]

SELECTED_ITEM_PARAMETERS: ItemParameters = {
    'background_color': SUCCESS_COLOR,
    'icon': '󰱒',
}
UNSELECTED_ITEM_PARAMETERS: ItemParameters = {
    'icon': '󰄱',
}


class UboPageWidget(PageWidget):
    """Base class for all UBO pages."""

    id: str = StringProperty()


class UboPromptWidget(PromptWidget, UboPageWidget):
    """Base class for all UBO prompts."""


class RawContentViewer(UboPageWidget):
    """Kivy widget for displaying raw content in a scrollable view."""

    text: str = StringProperty()

    def go_up(self) -> None:
        """Scroll up the error report."""
        self.ids.scrollable_widget.y = max(
            self.ids.scrollable_widget.y - dp(100),
            self.ids.container.y
            - (self.ids.scrollable_widget.height - self.ids.container.height),
        )

    def go_down(self) -> None:
        """Scroll down the error report."""
        self.ids.scrollable_widget.y = min(
            self.ids.scrollable_widget.y + dp(100),
            self.ids.container.y,
        )


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('raw_content_viewer.kv')
    .resolve()
    .as_posix(),
)
