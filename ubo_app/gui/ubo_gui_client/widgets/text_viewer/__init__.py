"""Raw text viewer widget."""

from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty

from ubo_gui_client.gui_utils import UboPageWidget


class RawTextViewer(UboPageWidget):
    """Kivy widget for displaying text in a scrollable view."""

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
    pathlib.Path(__file__).parent.joinpath('text_viewer.kv').resolve().as_posix(),
)
