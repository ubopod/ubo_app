"""VSCode page widgets for the GUI client."""

from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.properties import NumericProperty, StringProperty
from ubo_gui_client.gui_utils import UboPageWidget


class VSCodeQRCodePage(UboPageWidget):
    """QR code page showing VSCode tunnel URL."""

    url = StringProperty()


class VSCodeLoginPage(UboPageWidget):
    """Login page for VSCode tunnel authentication."""

    stage: int = NumericProperty(0)
    url: str | None = StringProperty()
    code: str | None = StringProperty()


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('vscode_pages.kv').resolve().as_posix(),
)
