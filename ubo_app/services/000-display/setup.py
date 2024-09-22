"""Sets up the display for the Raspberry Pi and manages its state."""

from __future__ import annotations

splash_screen = None


def init_service() -> None:
    """Initialize the display service."""
    from ubo_app import display
    from ubo_app.constants import HEIGHT, WIDTH

    if splash_screen:
        display.render_block((0, 0, WIDTH - 1, HEIGHT - 1), splash_screen)
    else:
        display.render_blank()
