"""QR code carousel render page widget."""

from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.properties import ListProperty, NumericProperty

from ubo_gui_client.gui_utils import UboPageWidget


class QRCodeCarouselRenderPage(UboPageWidget):
    """Generic QR code carousel page."""

    values: list[str] = ListProperty()
    labels: list[str] = ListProperty()
    index: int = NumericProperty(0)

    def go_down(self) -> None:
        """Show the next QR code."""
        if not self.values:
            return
        self.index = (self.index + 1) % len(self.values)
        self.ids.slider.animated_value = len(self.values) - 1 - self.index

    def go_up(self) -> None:
        """Show the previous QR code."""
        if not self.values:
            return
        self.index = (self.index - 1) % len(self.values)
        self.ids.slider.animated_value = len(self.values) - 1 - self.index


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('qr_code_carousel.kv')
    .resolve()
    .as_posix(),
)
