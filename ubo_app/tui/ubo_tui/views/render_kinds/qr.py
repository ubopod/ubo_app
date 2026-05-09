"""ASCII QR code renderer using the `qrcode` library."""

from __future__ import annotations

import io
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Smallest QR (version 3) needs ~33x33 modules + a quiet zone of 4 modules
# on each side. With half-block rendering (2 modules per character cell
# vertically), that's ~41 columns wide.
MIN_QR_WIDTH = 41


def render_qr_text(value: str, *, columns: int | None = None) -> str:
    """Return a monospaced QR rendering of ``value`` or a URL fallback.

    Uses the `qrcode` library's ``print_ascii`` with half-block characters so
    a square QR remains square on terminals (which render character cells
    roughly 2:1 height-to-width).

    If the terminal is too narrow (< MIN_QR_WIDTH columns), or QR generation
    fails for any reason, returns the input as plain text so the user can
    still copy/paste the URL.
    """
    if not value:
        return ""

    if columns is None:
        try:
            columns = os.get_terminal_size().columns
        except OSError:
            columns = MIN_QR_WIDTH

    if columns < MIN_QR_WIDTH:
        return f"{value}\n\n(terminal too narrow for QR; copy URL above)"

    try:
        import qrcode
    except ImportError:
        logger.warning("qrcode library not installed; falling back to URL text")
        return value

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=2,
        )
        qr.add_data(value)
        qr.make(fit=True)
        buffer = io.StringIO()
        qr.print_ascii(out=buffer, invert=True, tty=False)
        return buffer.getvalue().rstrip("\n")
    except Exception:
        logger.exception("QR generation failed for value of length %d", len(value))
        return value
