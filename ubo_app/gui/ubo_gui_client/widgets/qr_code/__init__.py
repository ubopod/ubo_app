"""QR code render page widget."""

from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.properties import StringProperty

from ubo_gui_client.gui_utils import UboPageWidget


class QRCodeRenderPage(UboPageWidget):
    """Generic QR code page with an optional display label."""

    value: str = StringProperty()
    label: str = StringProperty()


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('qr_code.kv').resolve().as_posix(),
)
