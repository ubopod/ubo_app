"""Generic reusable render widgets for the GUI client."""

from __future__ import annotations

import pathlib

from kivy.graphics.texture import Texture
from kivy.lang.builder import Builder
from kivy.properties import (
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)

from ubo_gui_client.gui_utils import RawImageViewer, RawTextViewer, UboPageWidget


class QRCodeRenderPage(UboPageWidget):
    """Generic QR code page with an optional display label."""

    value: str = StringProperty()
    label: str = StringProperty()


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


class StatusRenderPage(UboPageWidget):
    """Generic centered status page."""

    icon: str = StringProperty()
    text: str = StringProperty()
    icon_size: int = NumericProperty(56)
    text_font_size: int = NumericProperty(32)


class FrameStreamRenderPage(UboPageWidget):
    """Generic RGB frame stream page."""

    texture: Texture = ObjectProperty(None, allownone=True)

    def update_frame(self, data: bytes, width: int, height: int) -> None:
        """Update the displayed frame from raw RGB bytes."""
        texture = Texture.create(size=(width, height), colorfmt='rgb')
        texture.blit_buffer(data, colorfmt='rgb', bufferfmt='ubyte')
        texture.flip_vertical()
        self.texture = texture


GENERIC_RENDER_WIDGETS: dict[str, type[UboPageWidget]] = {
    'qr_code': QRCodeRenderPage,
    'qr_code_carousel': QRCodeCarouselRenderPage,
    'status': StatusRenderPage,
    'text_viewer': RawTextViewer,
    'image_viewer': RawImageViewer,
    'frame_stream': FrameStreamRenderPage,
}


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('generic_render.kv').resolve().as_posix(),
)
