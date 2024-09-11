"""Renders the QR code of the container's url (ip and port)."""

from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.properties import ListProperty, NumericProperty, StringProperty
from ubo_gui.page import PageWidget


class DockerQRCodePage(PageWidget):
    """QR code for the container's url (ip and port)."""

    ips: list[str] = ListProperty()
    port: str = StringProperty()
    index: int = NumericProperty(0)

    def go_down(self: DockerQRCodePage) -> None:
        """Go down."""
        self.index = (self.index + 1) % len(self.ips)
        self.ids.slider.animated_value = len(self.ips) - 1 - self.index

    def go_up(self: DockerQRCodePage) -> None:
        """Go up."""
        self.index = (self.index - 1) % len(self.ips)
        self.ids.slider.animated_value = len(self.ips) - 1 - self.index


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('docker_qrcode_page.kv')
    .resolve()
    .as_posix(),
)
