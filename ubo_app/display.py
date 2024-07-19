"""Provides the adafruit display tools."""

from __future__ import annotations

import atexit
from typing import TYPE_CHECKING, cast

import numpy as np
from adafruit_rgb_display.st7789 import ST7789

if TYPE_CHECKING:
    from threading import Thread

    from numpy._typing import NDArray


from ubo_app.constants import BYTES_PER_PIXEL
from ubo_app.utils import IS_RPI
from ubo_app.utils.fake import Fake

if IS_RPI:
    import board
    import digitalio

    cs_pin = digitalio.DigitalInOut(board.CE0)
    dc_pin = digitalio.DigitalInOut(board.D25)
    reset_pin = digitalio.DigitalInOut(board.D24)
    spi = board.SPI()


def setup_display() -> ST7789:
    """Set the display for the Raspberry Pi."""
    if IS_RPI:
        from ubo_app.constants import HEIGHT, WIDTH

        display = ST7789(
            spi,
            height=HEIGHT,
            width=WIDTH,
            y_offset=80,
            x_offset=0,
            cs=cs_pin,
            dc=dc_pin,
            rst=reset_pin,
            baudrate=60000000,
        )
    else:
        display = cast(ST7789, Fake())

    return display


def render_on_display(
    *,
    rectangle: tuple[int, int, int, int],
    data: NDArray[np.uint8],
    data_hash: int,
    last_render_thread: Thread,
) -> None:
    """Transfer data to the display via SPI controller."""
    if IS_RPI and state.is_running:
        from ubo_app.logging import logger

        logger.verbose('Rendering frame', extra={'data_hash': data_hash})

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
        state.block(rectangle, data_bytes)


def pause() -> None:
    """Pause the display."""
    state.is_running = False


def resume() -> None:
    """Resume the display."""
    state.is_running = True


class _State:
    """The state of the display."""

    is_running = True
    display = setup_display()

    def __init__(self: _State, splash_screen: bytes | None = None) -> None:
        from ubo_app.constants import HEIGHT, WIDTH

        self.block(
            (0, 0, WIDTH - 1, HEIGHT - 1),
            bytes(WIDTH * HEIGHT * BYTES_PER_PIXEL)
            if splash_screen is None
            else splash_screen,
        )
        atexit.register(
            lambda: self.block(
                (0, 0, WIDTH - 1, HEIGHT - 1),
                np.zeros((WIDTH, HEIGHT, BYTES_PER_PIXEL), dtype=np.uint8).tobytes(),
            ),
        )

    def block(
        self: _State,
        rectangle: tuple[int, int, int, int],
        data_bytes: bytes,
        *,
        bypass_pause: bool = False,
    ) -> None:
        """Block the display."""
        if self.is_running or bypass_pause:
            self.display._block(*rectangle, data_bytes)  # noqa: SLF001


state = _State()
