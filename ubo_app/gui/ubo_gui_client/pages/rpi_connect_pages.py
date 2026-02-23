"""RPi Connect page widgets for the GUI client."""

from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.properties import NumericProperty, StringProperty
from ubo_gui_client.gui_utils import UboPageWidget


class RPiConnectQRCodePage(UboPageWidget):
    """QR code page for RPi Connect URL."""

    url = StringProperty(defaultvalue='https://connect.raspberrypi.com/devices')


class RPiConnectSignInPage(UboPageWidget):
    """Sign-in page for RPi Connect authentication."""

    stage: int = NumericProperty(0)
    url: str | None = StringProperty()


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('rpi_connect_pages.kv')
    .resolve()
    .as_posix(),
)
