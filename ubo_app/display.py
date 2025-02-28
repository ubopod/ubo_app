"""Provides the adRegion display tools."""

from __future__ import annotations

import time
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
    from headless_kivy.config import Region


from ubo_app.constants import HEIGHT, WIDTH

if IS_RPI:
    import board
    import digitalio

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
        baudrate=70_000_000,
    )
else:
    display = cast(ST7789, Fake())


def render_on_display(*, regions: list[Region]) -> None:
    """Transfer data to the display via SPI controller."""
    for region in regions:
        rectangle = region['rectangle']
        data = region['data'].astype(np.uint16)
        color = (
            ((data[:, :, 0] & 0xF8) << 8)
            | ((data[:, :, 1] & 0xFC) << 3)
            | (data[:, :, 2] >> 3)
        ).copy()
        data_bytes = (
            color.astype(np.uint16).view(np.uint8).reshape(-1, 2)[:, ::-1].tobytes()
        )
        render_block(
            (
                rectangle[1],
                rectangle[0],
                rectangle[3] - 1,
                rectangle[2] - 1,
            ),
            data_bytes,
        )

    from kivy.metrics import dp

    density = dp(1)

    def generate_render_actions(
        region: Region,
    ) -> tuple[DisplayRenderEvent, DisplayCompressedRenderEvent]:
        data = region['data'].tobytes()
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        return (
            DisplayRenderEvent(
                data=data,
                rectangle=region['rectangle'],
                density=density,
            ),
            DisplayCompressedRenderEvent(
                compressed_data=compressor.compress(data) + compressor.flush(),
                rectangle=region['rectangle'],
                density=density,
            ),
        )

    store._dispatch(  # noqa: SLF001
        [event for region in regions for event in generate_render_actions(region)],
    )


original_block = display._block  # noqa: SLF001


@store.view(
    lambda state: state.display.is_paused if hasattr(state, 'display') else False,
)
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
    if IS_RPI:
        original_block(0, 0, WIDTH - 1, HEIGHT - 1, b'\x00\x00' * WIDTH * HEIGHT)
        time.sleep(0.2)
        original_block(0, 0, WIDTH - 1, HEIGHT - 1, b'\x00\x00' * WIDTH * HEIGHT)


splash_screen = None
if splash_screen:
    render_block((0, 0, WIDTH - 1, HEIGHT - 1), splash_screen)
else:
    render_blank()
