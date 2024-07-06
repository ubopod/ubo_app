"""Provides the adafruit display tools."""

from __future__ import annotations

import atexit
from typing import TYPE_CHECKING

import numpy as np
from headless_kivy.logger import logger

from ubo_app.constants import HEIGHT, WIDTH

if TYPE_CHECKING:
    from threading import Thread

    from numpy._typing import NDArray


from ubo_app.utils import IS_RPI
from ubo_app.utils.fake import Fake

if not IS_RPI:
    import sys

    sys.modules['adafruit_rgb_display.st7789'] = Fake()
from adafruit_rgb_display.st7789 import (  # pyright: ignore [reportMissingImports=false]
    ST7789,
)


def setup_display(width: int, height: int) -> ST7789:
    """Set the display for the Raspberry Pi."""
    splash_screen: bytes | None = None

    if IS_RPI:
        import board
        import digitalio

        cs_pin = digitalio.DigitalInOut(board.CE0)
        dc_pin = digitalio.DigitalInOut(board.D25)
        reset_pin = digitalio.DigitalInOut(board.D24)
        spi = board.SPI()
        display = ST7789(
            spi,
            height=height,
            width=width,
            y_offset=80,
            x_offset=0,
            cs=cs_pin,
            dc=dc_pin,
            rst=reset_pin,
            baudrate=60000000,
        )
        display._block(  # noqa: SLF001
            0,
            0,
            width - 1,
            height - 1,
            bytes(width * height * 2) if splash_screen is None else splash_screen,
        )
        atexit.register(
            lambda: display._block(  # noqa: SLF001
                0,
                0,
                width - 1,
                height - 1,
                bytes(width * height * 2),
            ),
        )
    else:
        display = Fake()

    return display


def render_on_display(
    *,
    rectangle: tuple[int, int, int, int],
    data: NDArray[np.uint8],
    data_hash: int,
    last_render_thread: Thread,
) -> None:
    """Transfer data to the display via SPI controller."""
    if IS_RPI and is_running:
        logger.debug(f'Rendering frame with hash "{data_hash}"')

        data = data.astype(np.uint16)
        color = (
            ((data[:, :, 0] & 0xF8) << 8)
            | ((data[:, :, 1] & 0xFC) << 3)
            | (data[:, :, 2] >> 3)
        )
        data_bytes = bytes(
            np.dstack(((color >> 8) & 0xFF, color & 0xFF)).flatten().tolist(),
        )

        # Wait for the last render thread to finish
        if last_render_thread:
            last_render_thread.join()

        # Only render when running on a Raspberry Pi
        if display:
            display._block(*rectangle, data_bytes)  # noqa: SLF001


def pause() -> None:
    """Pause the display."""
    global is_running  # noqa: PLW0603
    is_running = False


def resume() -> None:
    """Resume the display."""
    global is_running  # noqa: PLW0603
    is_running = True


is_running = True
display = setup_display(WIDTH, HEIGHT)
