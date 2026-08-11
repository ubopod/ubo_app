"""QR code render page widget."""

from __future__ import annotations

import pathlib
import re

from kivy.lang.builder import Builder
from kivy.properties import AliasProperty, StringProperty

from ubo_gui_client.gui_utils import UboPageWidget

URL_LABEL_PATTERN = re.compile(r'^\s*https?://', re.IGNORECASE)


class QRCodeRenderPage(UboPageWidget):
    """Generic QR code page with an optional display label."""

    value: str = StringProperty()
    label: str = StringProperty()
    # Shown on its own line under the label, for text that accompanies the code
    # without being part of it — e.g. a device code to type after scanning.
    caption: str = StringProperty()

    def _get_display_label(self) -> str:
        """Drop a label that only repeats the URL already inside the QR.

        There is no browser on this screen, so a URL is not actionable text —
        it exists to be scanned, and the QR already carries it. Printing it
        costs the room the QR needs: the code shrinks to fit the wrapped URL
        and can end up too small for a phone camera to resolve.

        Labels that are *not* URLs are the ones the user has to read — a
        device code, an ``ip:port`` — so those stay.
        """
        return '' if URL_LABEL_PATTERN.match(self.label) else self.label

    # Uncached deliberately: the getter is a regex match on a short string, so
    # caching buys nothing, and this client has already been bitten once by
    # AliasProperty cache staleness (see the note in `view_renderer.py`).
    display_label: str = AliasProperty(getter=_get_display_label, bind=['label'])


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('qr_code.kv').resolve().as_posix(),
)
