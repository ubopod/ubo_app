"""Provides the adRegion display tools."""

from __future__ import annotations

import time
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
from ubo_app.utils.eeprom import get_eeprom_data

if TYPE_CHECKING:
    from collections.abc import Callable

    from headless_kivy.config import Region


from ubo_app.constants import HEIGHT, WIDTH


class Display:
    """Display class."""

    def __init__(self: Display) -> None:
        """Initialize the display."""
        if IS_RPI:
            eeprom_data = get_eeprom_data()

            if (
                eeprom_data is not None
                and 'lcd' in eeprom_data
                and eeprom_data['lcd'] is not None
                and eeprom_data['lcd']['model'] == 'st7789'
            ):
                import board
                import digitalio

                self.cs_pin = digitalio.DigitalInOut(board.CE0)
                self.dc_pin = digitalio.DigitalInOut(board.D25)
                self.reset_pin = digitalio.DigitalInOut(board.D24)
                self.spi = board.SPI()
                self.display = ST7789(
                    self.spi,
                    height=HEIGHT,
                    width=WIDTH,
                    y_offset=80,
                    x_offset=0,
                    cs=self.cs_pin,
                    dc=self.dc_pin,
                    rst=self.reset_pin,
                    baudrate=70_000_000,
                )
            else:
                self.display = None
        else:
            self.display = cast('ST7789', Fake())

    def turn_off(self: Display) -> None:
        """Turn off the display and free resources."""
        if self.display:
            render = self.display._block  # noqa: SLF001
            self.display = None
            self.render_blank(render)
            del render

            if IS_RPI:
                self.cs_pin.deinit()
                self.dc_pin.deinit()
                self.reset_pin.deinit()
                self.spi.deinit()

                import lgpio  # pyright: ignore [reportMissingModuleSource]
                from adafruit_blinka.microcontroller.generic_linux.lgpio_pin import CHIP

                lgpio.gpiochip_close(CHIP)

    def render_blank(self: Display, render_function: Callable | None = None) -> None:
        """Render a blank screen."""
        if IS_RPI:
            if not render_function and self.display is not None:
                render_function = self.display._block  # noqa: SLF001
            if render_function:
                render_function(
                    0,
                    0,
                    WIDTH - 1,
                    HEIGHT - 1,
                    b'\x00\x00' * WIDTH * HEIGHT,
                )
                time.sleep(0.2)
                render_function(
                    0,
                    0,
                    WIDTH - 1,
                    HEIGHT - 1,
                    b'\x00\x00' * WIDTH * HEIGHT,
                )

    def render_block(
        self: Display,
        *,
        rectangle: tuple[int, int, int, int],
        data_bytes: bytes,
        bypass_pause: bool = False,
    ) -> None:
        """Block the display."""

        @store.with_state(
            lambda state: state.display.is_paused
            if hasattr(state, 'display')
            else False,
        )
        def render(is_paused: bool) -> None:  # noqa: FBT001
            if self.display is not None and (not is_paused or bypass_pause):
                self.display._block(*rectangle, data_bytes)  # noqa: SLF001

        render()


display = Display()


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
        display.render_block(
            rectangle=(
                rectangle[1],
                rectangle[0],
                rectangle[3] - 1,
                rectangle[2] - 1,
            ),
            data_bytes=data_bytes,
        )

    from kivy.metrics import dp

    density = dp(1)

    def generate_render_actions(
        region: Region,
    ) -> tuple[DisplayRenderEvent, DisplayCompressedRenderEvent]:
        import zlib

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


splash_screen = None
if splash_screen:
    display.render_block(
        rectangle=(0, 0, WIDTH - 1, HEIGHT - 1),
        data_bytes=splash_screen,
    )
else:
    display.render_blank()
