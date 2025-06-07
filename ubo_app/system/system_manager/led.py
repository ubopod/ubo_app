# ruff: noqa: D100, D101, D102, D103, D104, D107, PLR2004
from __future__ import annotations

import logging
import time
import warnings
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, cast

import board
from fake import Fake

from ubo_app.logger import get_logger

if Path('/proc/device-tree/model').read_text().startswith('Raspberry Pi 5'):
    import sys

    sys.modules['neopixel'] = Fake()

import neopixel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from adafruit_blinka.microcontroller.generic_micropython import Pin

    from ubo_app.store.services.rgb_ring import RgbColor

BRIGHTNESS = 1.0
NUM_LEDS = 27
ORDER = neopixel.GRB


class LEDManager:
    def __init__(self: LEDManager) -> None:
        self.logger = get_logger('system-manager')
        self._last_thread = None
        self.logger.setLevel(logging.DEBUG)
        self.logger.info('Initialising LEDManager...')

        self.led_ring_present = True
        self.current_color = None
        self._stop: bool = False
        self.current_bright_one = 1
        self.brightness = BRIGHTNESS
        if self.brightness < 0 or self.brightness > 1:
            warnings.warn(
                'Invalid brightness value in config file',
                Warning,
                stacklevel=2,
            )
            self.brightness = 1.0

        self.num_leds = NUM_LEDS

        self.pixels = neopixel.NeoPixel(
            pin=cast('Pin', board.D12),
            n=self.num_leds,
            brightness=1,
            bpp=3,
            auto_write=False,
            pixel_order=ORDER,
        )

    def stop(self: LEDManager) -> None:
        self._stop = True

    def adjust_brightness(
        self: LEDManager,
        color: RgbColor,
    ) -> RgbColor:
        b = self.brightness
        return (color[0] * b, color[1] * b, color[2] * b)

    def set_brightness(self: LEDManager, b: float) -> None:
        self.brightness = b

    def set_enabled(self: LEDManager, *, enabled: bool = True) -> None:
        if enabled is False:
            self.blank()
        self.led_ring_present = enabled

    def set_all(self: LEDManager, color: RgbColor) -> None:
        if not self.led_ring_present:
            return
        color = self.adjust_brightness(color)
        self.pixels.fill(color)
        self.pixels.show()

    def blank(self: LEDManager) -> None:
        if not self.led_ring_present:
            return
        self.set_all((0, 0, 0))

    def run_initialization_loop(self: LEDManager) -> None:
        self.run_command_thread_safe(
            ['spinning_wheel', '255', '255', '255', '50', '6', '100'],
        )

    def fill_upto(
        self: LEDManager,
        color: RgbColor,
        percentage: float,
        wait: float,
    ) -> None:
        if not self.led_ring_present:
            return
        for i in range(int(self.num_leds * percentage)):
            if self._stop is True:
                self.blank()
                return
            self.pixels[i] = self.adjust_brightness(color)
            time.sleep(wait / 1000)
            self.pixels.show()
        time.sleep(5 * wait / 1000)

    def fill_downfrom(
        self: LEDManager,
        color: RgbColor,
        percentage: float,
        wait: float,
    ) -> None:
        if not self.led_ring_present:
            return
        color = self.adjust_brightness(color)
        self.pixels[: int(self.num_leds * percentage)] = [color] * int(
            self.num_leds * percentage,
        )
        self.pixels.show()
        time.sleep(5 * wait / 1000)
        for i in range(int(self.num_leds * percentage) - 1, -1, -1):
            if self._stop is True:
                self.blank()
                return
            self.pixels[i] = (0, 0, 0)
            time.sleep(wait / 1000)
            self.pixels.show()

    def progress_wheel_step(self: LEDManager, color: RgbColor) -> None:
        if not self.led_ring_present:
            return
        dim_factor = 20
        color = self.adjust_brightness(color)
        self.set_all(
            (color[0] / dim_factor, color[1] / dim_factor, color[2] / dim_factor),
        )
        self.current_bright_one = (self.current_bright_one + 1) % self.num_leds
        before = (self.current_bright_one - 1) % self.num_leds
        if before < 0:
            before = self.num_leds + before
        after = (self.current_bright_one + 1) % self.num_leds

        self.pixels[before] = color
        self.pixels[after] = color
        self.pixels[self.current_bright_one] = color
        self.pixels.show()

    def wheel(self: LEDManager, pos: int) -> RgbColor:
        # Input a value 0 to 255 to get a color value.
        # The colors are a transition r - g - b - back to r.
        if pos < 0 or pos > 0b11111111:
            r = g = b = 0
        elif pos < 0b01010101:
            r = int(pos * 3)
            g = int(0b11111111 - pos * 3)
            b = 0
        elif pos < 0b10101010:
            pos -= 0b1010101
            r = int(0b11111111 - pos * 3)
            g = 0
            b = int(pos * 3)
        else:
            pos -= 0b10101010
            r = 0
            g = int(pos * 3)
            b = int(0b11111111 - pos * 3)
        return (r, g, b) if ORDER in (neopixel.RGB, neopixel.GRB) else (r, g, b, 0)

    # wait is in milliseconds
    def rainbow(
        self: LEDManager,
        rounds: int = 50,
        wait: float = 1,
    ) -> None:
        if not self.led_ring_present:
            return
        counter = 0
        while True:
            for j in range(255):
                if self._stop is True:
                    self.blank()
                    return
                for i in range(self.num_leds):
                    pixel_index = (i * 256 // self.num_leds) + j
                    (r, g, b, *_) = self.wheel(pixel_index & 255)
                    self.pixels[i] = (
                        r * self.brightness,
                        g * self.brightness,
                        b * self.brightness,
                    )
                self.pixels.show()
                time.sleep(wait / 1000 / 256)
            counter += 1
            if counter == rounds:
                break
        self.blank()

    def pulse(self: LEDManager, color: RgbColor, wait: float, repetitions: int) -> None:
        # wait is in milliseconds
        # repetitions is the number of retepting pluses
        if not self.led_ring_present:
            return
        dim_steps = 10
        color = self.adjust_brightness(color)
        counter = 0
        while True:
            for i in range(dim_steps):
                if self._stop is True:
                    self.blank()
                    return
                m = i / dim_steps
                self.pixels.fill((color[0] * m, color[1] * m, color[2] * m))
                self.pixels.show()
                time.sleep(wait / 10000)
            for i in range(1, dim_steps):
                if self._stop is True:
                    self.blank()
                    return
                j = (dim_steps - i) / dim_steps
                self.pixels.fill((color[0] * j, color[1] * j, color[2] * j))
                self.pixels.show()
                time.sleep(wait / 10000)
            counter += 1
            if counter == repetitions:
                break
        self.blank()

    def blink(self: LEDManager, color: RgbColor, wait: float, repetitions: int) -> None:
        # wait is in milliseconds
        # repetitions is the number of blinks
        if not self.led_ring_present:
            return
        color = self.adjust_brightness(color)
        counter = 0
        while True:
            if self._stop is True:
                self.blank()
                return
            self.pixels.fill((color[0], color[1], color[2]))
            self.pixels.show()
            time.sleep(wait / 1000)
            self.blank()
            time.sleep(1.5 * wait / 1000)
            counter += 1
            if counter == repetitions:
                break

    def spinning_wheel(
        self: LEDManager,
        color: RgbColor,
        wait: float = 1,
        length: int = 5,
        repetitions: int = 5,
    ) -> None:
        if not self.led_ring_present:
            return
        color = self.adjust_brightness(color)
        ring: list[RgbColor] = [(0, 0, 0)] * self.num_leds
        ring[0:length] = [color] * (length)
        if length > self.num_leds:
            warnings.warn(
                f'invalid light strip length! must be under {self.num_leds}',
                Warning,
                stacklevel=2,
            )
            return
        counter = 0
        while True:
            for i in range(self.num_leds):
                if self._stop is True:
                    self.blank()
                    return
                shifted = ring[i:] + ring[:i]
                # for j in self.num_leds
                self.pixels[:] = shifted
                self.pixels.show()
                time.sleep(wait / 1000)
            counter += 1
            if counter == repetitions:
                break
        self.blank()

    def progress_wheel(self: LEDManager, color: RgbColor, percentage: float) -> None:
        # percentage is a float value between 0 and 1
        if not self.led_ring_present:
            return
        color = self.adjust_brightness(color)
        ring: list[RgbColor] = [(0, 0, 0)] * self.num_leds
        ring[0 : int(self.num_leds * percentage)] = [color] * (
            int(self.num_leds * percentage)
        )
        self.pixels[:] = ring
        self.pixels.show()

    def run_command_thread_safe(self: LEDManager, incoming: Sequence[str]) -> None:
        if self._last_thread:
            self.stop()
            self._last_thread.join()

        self.logger.info('---starting led new thread--', extra={'incoming': incoming})
        self._last_thread = Thread(target=self.run_command, args=(incoming,))
        self._last_thread.start()

    def run_command(self: LEDManager, incoming: Sequence[str]) -> None:  # noqa: C901, PLR0912
        self.logger.info('Executing LED command', extra={'incoming': incoming})
        self.incoming = incoming
        self._stop = False
        sequence = ' '.join(incoming)
        for command_string in sequence.split('|'):
            command = command_string.strip().split()
            if command[0] == 'set_enabled' and len(command) == 2:
                self.set_enabled(enabled=command[1] == '1')
            # set brightness of LEDs
            if command[0] == 'set_brightness' and len(command) == 2:
                brightness_value = float(command[1])
                if 0 < brightness_value <= 1:
                    self.set_brightness(brightness_value)
            if command[0] == 'set_all' and len(command) == 4:
                self.set_all((int(command[1]), int(command[2]), int(command[3])))
            if command[0] == 'blank':
                self.blank()
            if command[0] == 'rainbow' and len(command) == 3:
                self.rainbow(int(command[1]), float(command[2]))
            if command[0] == 'pulse' and len(command) == 6:
                # pulse(self, color, wait, repetitions):
                self.pulse(
                    (int(command[1]), int(command[2]), int(command[3])),
                    wait=int(command[4]),
                    repetitions=int(command[5]),
                )
            if command[0] == 'blink' and len(command) == 6:
                # blink(self, color, wait, repetitions):
                self.blink(
                    (int(command[1]), int(command[2]), int(command[3])),
                    wait=int(command[4]),
                    repetitions=int(command[5]),
                )
            if command[0] == 'progress_wheel_step' and len(command) == 4:
                self.progress_wheel_step(
                    (int(command[1]), int(command[2]), int(command[3])),
                )
            if command[0] == 'spinning_wheel':  # noqa: SIM102
                # spinning_wheel(self, color, wait, length, repetitions):
                if len(command) == 7:
                    self.spinning_wheel(
                        (int(command[1]), int(command[2]), int(command[3])),
                        wait=int(command[4]),
                        length=int(command[5]),
                        repetitions=int(command[6]),
                    )
            if command[0] == 'progress_wheel' and len(command) == 5:
                # progress_wheel(self, color, percentage):
                self.progress_wheel(
                    (int(command[1]), int(command[2]), int(command[3])),
                    percentage=float(command[4]),
                )
            if command[0] == 'fill_upto' and len(command) == 6:
                # fill_upto(self, color, percentage, wait):
                self.fill_upto(
                    (int(command[1]), int(command[2]), int(command[3])),
                    wait=int(command[4]),
                    percentage=float(command[5]),
                )
            if command[0] == 'fill_downfrom' and len(command) == 6:
                # fill_upto(self, color, percentage, wait):
                self.fill_downfrom(
                    (int(command[1]), int(command[2]), int(command[3])),
                    wait=int(command[4]),
                    percentage=float(command[5]),
                )
        self._stop = False
