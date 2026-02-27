"""Camera viewfinder page widget for the GUI client."""

from __future__ import annotations

import pathlib

from kivy.graphics.texture import Texture
from kivy.lang.builder import Builder
from kivy.properties import ObjectProperty

from ubo_gui_client.gui_utils import UboPageWidget


class CameraViewfinderPage(UboPageWidget):
    """Full-screen camera viewfinder that displays streamed frames."""

    texture: Texture = ObjectProperty(None, allownone=True)

    def update_frame(self, data: bytes, width: int, height: int) -> None:
        """Update the displayed frame from raw RGB bytes."""
        texture = Texture.create(size=(width, height), colorfmt='rgb')
        texture.blit_buffer(data, colorfmt='rgb', bufferfmt='ubyte')
        texture.flip_vertical()
        self.texture = texture


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('camera_viewfinder.kv')
    .resolve()
    .as_posix(),
)
