"""Status render page widget."""

from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.properties import NumericProperty, StringProperty

from ubo_gui_client.gui_utils import UboPageWidget


class StatusRenderPage(UboPageWidget):
    """Generic centered status page."""

    icon: str = StringProperty()
    text: str = StringProperty()
    icon_size: int = NumericProperty(56)
    text_font_size: int = NumericProperty(32)


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('status.kv').resolve().as_posix(),
)
