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
    # Shown on its own line under the label, for text that accompanies the code
    # without being part of it — e.g. a device code to type after scanning.
    caption: str = StringProperty()


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('qr_code.kv').resolve().as_posix(),
)
