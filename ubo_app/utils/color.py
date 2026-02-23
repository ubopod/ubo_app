"""Color utility functions replacing kivy.utils color helpers."""

from __future__ import annotations


def hex_to_color(hex_str: str) -> tuple[float, float, float, float]:
    """Convert hex color string to (r, g, b, a) tuple with values 0-1.

    Replaces kivy.utils.get_color_from_hex.
    """
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 3:  # noqa: PLR2004
        hex_str = ''.join(c * 2 for c in hex_str)
    if len(hex_str) == 6:  # noqa: PLR2004
        hex_str += 'ff'
    r = int(hex_str[0:2], 16) / 255.0
    g = int(hex_str[2:4], 16) / 255.0
    b = int(hex_str[4:6], 16) / 255.0
    a = int(hex_str[6:8], 16) / 255.0
    return (r, g, b, a)


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert hex color string to (r, g, b) tuple with values 0-255."""
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 3:  # noqa: PLR2004
        hex_str = ''.join(c * 2 for c in hex_str)
    return (
        int(hex_str[0:2], 16),
        int(hex_str[2:4], 16),
        int(hex_str[4:6], 16),
    )


def escape_markup(text: str) -> str:
    """Escape markup characters in text.

    Replaces kivy.utils.escape_markup.
    """
    return text.replace('&', '&amp;').replace('[', '&bl;').replace(']', '&br;')
