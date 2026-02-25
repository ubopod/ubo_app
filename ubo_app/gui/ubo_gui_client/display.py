"""Display driver for SPI-connected ST7789 display."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, cast

import numpy as np
from adafruit_rgb_display.st7789 import ST7789
from fake import Fake

from ubo_gui_client.constants import (
    DISPLAY_BAUDRATE,
    HEIGHT,
    IS_RPI,
    WIDTH,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from headless_kivy.config import Region

logger = logging.getLogger(__name__)


class Display:
    """Display class for SPI hardware driver."""

    def __init__(self: Display) -> None:
        """Initialize the display."""
        self.cs_pin = None
        self.dc_pin = None
        self.reset_pin = None
        self.backlight_pin = None
        self.spi = None
        self.display = None
        if IS_RPI:
            from ubo_gui_client.eeprom import get_eeprom_data

            eeprom_data = get_eeprom_data()

            if (
                eeprom_data['lcd'] is not None
                and eeprom_data['lcd']['model'] == 'st7789'
            ):
                logger.debug('LCD display found.')
                import board
                import digitalio

                self.cs_pin = digitalio.DigitalInOut(board.CE0)
                self.dc_pin = digitalio.DigitalInOut(board.D25)
                self.spi = board.SPI()
                self.display = ST7789(
                    self.spi,
                    height=HEIGHT,
                    width=WIDTH,
                    y_offset=80,
                    x_offset=0,
                    cs=self.cs_pin,
                    dc=self.dc_pin,
                    baudrate=DISPLAY_BAUDRATE,
                )

                self.backlight_pin = digitalio.DigitalInOut(board.D26)
                self.backlight_pin.switch_to_output()
                self.backlight_pin.value = True
        else:
            logger.debug('No physical display found.')
            self.display = cast('ST7789', Fake())

    def turn_off(self: Display) -> None:
        """Turn off the display and free resources."""
        if self.display:
            render = self.display._block  # noqa: SLF001
            self.display = None
            self.render_blank(render)
            del render

            if IS_RPI:
                from adafruit_blinka.agnostic import detector

                if detector.board.any_raspberry_pi_5_board:
                    import lgpio  # pyright: ignore[reportMissingImports,reportMissingModuleSource]
                    from adafruit_blinka.microcontroller.generic_linux import lgpio_pin

                    lgpio.gpiochip_close(lgpio_pin.CHIP)
                else:
                    import board
                    from RPi import GPIO  # pyright: ignore [reportMissingModuleSource]

                    if board.CE0.id:
                        GPIO.cleanup(board.CE0.id)
                    if board.D25.id:
                        GPIO.cleanup(board.D25.id)
                    if board.D26.id:
                        GPIO.cleanup(board.D26.id)

    def set_backlight(self: Display, enabled: bool) -> None:  # noqa: FBT001
        """Control backlight state."""
        if IS_RPI and self.backlight_pin is not None:
            self.backlight_pin.value = enabled
            logger.debug(
                'Backlight state changed',
                extra={'enabled': enabled},
            )

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
    ) -> None:
        """Render a block on the display."""
        if self.display is not None:
            self.display._block(*rectangle, data_bytes)  # noqa: SLF001


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


splash_screen = None
if splash_screen:
    display.render_block(
        rectangle=(0, 0, WIDTH - 1, HEIGHT - 1),
        data_bytes=splash_screen,
    )
else:
    display.render_blank()
