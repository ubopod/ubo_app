"""Provides the adafruit display tools."""

from __future__ import annotations

import zlib
from typing import TYPE_CHECKING, cast

import numpy as np
from adafruit_rgb_display.st7789 import ST7789
from fake import Fake

from ubo_app.store.main import store
from ubo_app.store.services.display import (
    DisplayCompressedRenderEvent,
    DisplayRenderEvent,
)
from ubo_app.utils import IS_RPI

if TYPE_CHECKING:
    from threading import Thread

    from numpy._typing import NDArray


if IS_RPI:
    import board
    import digitalio

    from ubo_app.constants import HEIGHT, WIDTH

    cs_pin = digitalio.DigitalInOut(board.CE0)
    dc_pin = digitalio.DigitalInOut(board.D25)
    reset_pin = digitalio.DigitalInOut(board.D24)
    spi = board.SPI()
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


def render_on_display(
    *,
    rectangle: tuple[int, int, int, int],
    data: NDArray[np.uint8],
    data_hash: int,
    last_render_thread: Thread,
) -> None:
    """Transfer data to the display via SPI controller."""
    data_ = data.astype(np.uint16)
    color = (
        ((data_[:, :, 0] & 0xF8) << 8)
        | ((data_[:, :, 1] & 0xFC) << 3)
        | (data_[:, :, 2] >> 3)
    )
    data_bytes = bytes(
        np.dstack(((color >> 8) & 0xFF, color & 0xFF)).flatten().tolist(),
    )
    if last_render_thread:
        last_render_thread.join()
    render_block(rectangle, data_bytes)
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    store._dispatch(  # noqa: SLF001
        [
            DisplayRenderEvent(
                data=data.tobytes(),
                data_hash=data_hash,
                rectangle=rectangle,
            ),
            DisplayCompressedRenderEvent(
                compressed_data=compressor.compress(data.tobytes())
                + compressor.flush(),
                data_hash=data_hash,
                rectangle=rectangle,
            ),
        ],
    )


@store.view(lambda state: state.display.is_paused)
def render_block(
    is_paused: bool,  # noqa: FBT001
    rectangle: tuple[int, int, int, int],
    data_bytes: bytes,
    *,
    bypass_pause: bool = False,
) -> None:
    """Block the display."""
    if not is_paused or bypass_pause:
        display._block(*rectangle, data_bytes)  # noqa: SLF001


def turn_off() -> None:
    """Turn off the display."""
    display._block = lambda *args, **kwargs: (args, kwargs)  # noqa: SLF001
    render_blank()


def render_blank() -> None:
    """Render a blank screen."""
    display.fill(0)
