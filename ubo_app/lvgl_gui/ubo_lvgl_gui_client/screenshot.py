"""Capture the LVGL screen as PNG (for the gRPC screenshot facility / CI).

Mirrors the Kivy client: on a ScreenshotEvent the client encodes the current
framebuffer to PNG and dispatches it back via ScreenshotDataAction. The core
saves it with the same tooling that handles Kivy window snapshots, enabling
apple-to-apple comparison and CI window-snapshot regression tests.
"""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING

import png

if TYPE_CHECKING:
    from ubo_lvgl_gui_client.bridge import Renderer


def _rgb565_to_rgb_rows(data: bytes, width: int, height: int) -> list[bytes]:
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray(width * 3)
        base = y * width * 2
        for x in range(width):
            i = base + x * 2
            v = data[i] | (data[i + 1] << 8)
            r5 = (v >> 11) & 0x1F
            g6 = (v >> 5) & 0x3F
            b5 = v & 0x1F
            row[x * 3] = (r5 << 3) | (r5 >> 2)
            row[x * 3 + 1] = (g6 << 2) | (g6 >> 4)
            row[x * 3 + 2] = (b5 << 3) | (b5 >> 2)
        rows.append(bytes(row))
    return rows


def capture(renderer: Renderer) -> tuple[bytes, str]:
    """Return (png_bytes, sha256_hex) of the current screen."""
    data, width, height = renderer.get_framebuffer()
    rows = _rgb565_to_rgb_rows(data, width, height)
    out = io.BytesIO()
    png.Writer(
        width=width,
        height=height,
        greyscale=False,  # pyright: ignore[reportArgumentType]
        bitdepth=8,
    ).write(out, rows)
    png_bytes = out.getvalue()
    return png_bytes, hashlib.sha256(png_bytes).hexdigest()
