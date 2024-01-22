# ruff: noqa: D100, D101, D102, D103, D104, D107, PLR2004
from __future__ import annotations

import grp
import logging
import os
import pwd
import socket
import stat
import sys
import time
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Sequence, cast

import board
import neopixel
from adafruit_blinka.microcontroller.generic_micropython import Pin
from ubo_gui.menu import warnings

from ubo_app.constants import USERNAME

if TYPE_CHECKING:
    from ubo_app.store.services.rgb_ring import Color

BRIGHTNESS = 1.0
NUM_LEDS = 27

LM_SOCKET_PATH = Path(os.getenv('RUNTIME_DIRECTORY', '/run/ubo')).joinpath(
    'ledmanagersocket.sock',
)
# The order of the pixel colors - RGB or GRB.
# Some NeoPixels have red and green reversed!
# For RGBW NeoPixels, simply change the ORDER to RGBW or GRBW.
ORDER = neopixel.GRB

logger = logging.getLogger('led-manager')
logger.setLevel(logging.DEBUG)
logger.debug('Initialising LED-Manager...')


class LEDManager:
    def __init__(self: LEDManager) -> None:
        self.led_ring_present = True
        self.current_color = None
        self.stop: bool = False
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
            pin=cast(Pin, board.D12),
            n=self.num_leds,
            brightness=1,
            bpp=3,
            auto_write=False,
            pixel_order=ORDER,
        )

    def adjust_brightness(
        self: LEDManager,
        color: Color,
    ) -> Color:
        b = self.brightness
        return (color[0] * b, color[1] * b, color[2] * b)

    def set_brightness(self: LEDManager, b: float) -> None:
        self.brightness = b

    def set_enabled(self: LEDManager, *, enabled: bool = True) -> None:
        if enabled is False:
            self.blank()
        self.led_ring_present = enabled

    def set_all(self: LEDManager, color: Color) -> None:
        if not self.led_ring_present:
            return
        color = self.adjust_brightness(color)
        self.pixels.fill(color)
        self.pixels.show()

    def blank(self: LEDManager) -> None:
        if not self.led_ring_present:
            return
        self.set_all((0, 0, 0))

    def fill_upto(
        self: LEDManager,
        color: Color,
        percentage: float,
        wait: float,
    ) -> None:
        if not self.led_ring_present:
            return
        for i in range(int(self.num_leds * percentage)):
            if self.stop is True:
                self.blank()
                return
            self.pixels[i] = self.adjust_brightness(color)
            time.sleep(wait / 1000)
            self.pixels.show()
        time.sleep(5 * wait / 1000)

    def fill_downfrom(
        self: LEDManager,
        color: Color,
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
            if self.stop is True:
                self.blank()
                return
            self.pixels[i] = (0, 0, 0)
            time.sleep(wait / 1000)
            self.pixels.show()

    def progress_wheel_step(self: LEDManager, color: Color) -> None:
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

    def wheel(self: LEDManager, pos: int) -> Color:
        # Input a value 0 to 255 to get a color value.
        # The colours are a transition r - g - b - back to r.
        if pos < 0 or pos > 0b11111111:
            r = g = b = 0
        elif pos < 0b01010101:
            r = int(pos * 3)
            g = int(0b11111111 - pos * 3)
            b = 0
        elif pos < 0b10101010:
            pos -= 85
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
        for _ in range(rounds):
            for j in range(255):
                if self.stop is True:
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
                time.sleep(wait / 1000)
        self.blank()

    def pulse(self: LEDManager, color: Color, wait: float, repetitions: int) -> None:
        # wait is in milliseconds
        # repetitions is the number of retepting pluses
        if not self.led_ring_present:
            return
        dim_steps = 10
        color = self.adjust_brightness(color)
        for _ in range(repetitions):
            for i in range(dim_steps):
                if self.stop is True:
                    self.blank()
                    return
                m = i / dim_steps
                self.pixels.fill((color[0] * m, color[1] * m, color[2] * m))
                self.pixels.show()
                time.sleep(wait / 10000)
            for i in range(1, dim_steps):
                if self.stop is True:
                    self.blank()
                    return
                j = (dim_steps - i) / dim_steps
                self.pixels.fill((color[0] * j, color[1] * j, color[2] * j))
                self.pixels.show()
                time.sleep(wait / 10000)
        self.blank()

    def blink(self: LEDManager, color: Color, wait: float, repetitions: int) -> None:
        # wait is in milliseconds
        # repetitions is the number of blinks
        if not self.led_ring_present:
            return
        color = self.adjust_brightness(color)
        for _ in range(repetitions):
            if self.stop is True:
                self.blank()
                return
            self.pixels.fill((color[0], color[1], color[2]))
            self.pixels.show()
            time.sleep(wait / 1000)
            self.blank()
            time.sleep(1.5 * wait / 1000)

    def spinning_wheel(
        self: LEDManager,
        color: Color,
        wait: float = 1,
        length: int = 5,
        repetitions: int = 5,
    ) -> None:
        if not self.led_ring_present:
            return
        color = self.adjust_brightness(color)
        ring: list[Color] = [(0, 0, 0)] * self.num_leds
        ring[0:length] = [color] * (length)
        if length > self.num_leds:
            warnings.warn(
                f'invalid light strip length! must be under {self.num_leds}',
                Warning,
                stacklevel=2,
            )
            return
        for _ in range(repetitions):
            for i in range(self.num_leds):
                if self.stop is True:
                    self.blank()
                    return
                shifted = ring[i:] + ring[:i]
                # for j in self.num_leds
                self.pixels[:] = shifted
                self.pixels.show()
                time.sleep(wait / 1000)
        self.blank()

    def progress_wheel(self: LEDManager, color: Color, percentage: float) -> None:
        # percentage is a float value between 0 and 1
        if not self.led_ring_present:
            return
        color = self.adjust_brightness(color)
        ring: list[Color] = [(0, 0, 0)] * self.num_leds
        ring[0 : int(self.num_leds * percentage)] = [color] * (
            int(self.num_leds * percentage)
        )
        self.pixels[:] = ring
        self.pixels.show()

    def run_command(self: LEDManager, incoming: Sequence[str]) -> None:  # noqa: C901, PLR0912
        logger.info('---executing command---')
        self.incoming = incoming
        self.stop = False
        if incoming[0] == 'set_enabled' and len(incoming) == 2:
            lm.set_enabled(enabled=incoming[1] == '1')
        # set brightness of LEDs
        if incoming[0] == 'set_brightness' and len(incoming) == 2:
            brightness_value = float(incoming[1])
            if 0 < brightness_value <= 1:
                self.set_brightness(brightness_value)
        if incoming[0] == 'set_all' and len(incoming) == 4:
            lm.set_all((int(incoming[1]), int(incoming[2]), int(incoming[3])))
        if incoming[0] == 'blank':
            self.blank()
        if incoming[0] == 'rainbow' and len(incoming) == 3:
            self.rainbow(int(incoming[1]), float(incoming[2]))
        if incoming[0] == 'pulse' and len(incoming) == 6:
            # pulse(self, color, wait, repetitions):
            self.pulse(
                (int(incoming[1]), int(incoming[2]), int(incoming[3])),
                wait=int(incoming[4]),
                repetitions=int(incoming[5]),
            )
        if incoming[0] == 'blink' and len(incoming) == 6:
            # blink(self, color, wait, repetitions):
            self.blink(
                (int(incoming[1]), int(incoming[2]), int(incoming[3])),
                wait=int(incoming[4]),
                repetitions=int(incoming[5]),
            )
        if incoming[0] == 'progress_wheel_step' and len(incoming) == 4:
            self.progress_wheel_step(
                (int(incoming[1]), int(incoming[2]), int(incoming[3])),
            )
        if incoming[0] == 'spinning_wheel':  # noqa: SIM102
            # spinning_wheel(self, color, wait, length, repetitions):
            if len(incoming) == 7:
                self.spinning_wheel(
                    (int(incoming[1]), int(incoming[2]), int(incoming[3])),
                    wait=int(incoming[4]),
                    length=int(incoming[5]),
                    repetitions=int(incoming[6]),
                )
        if incoming[0] == 'progress_wheel' and len(incoming) == 5:
            # progress_wheel(self, color, percentage):
            self.progress_wheel(
                (int(incoming[1]), int(incoming[2]), int(incoming[3])),
                percentage=float(incoming[4]),
            )
        if incoming[0] == 'fill_upto' and len(incoming) == 6:
            # fill_upto(self, color, percentage, wait):
            self.fill_upto(
                (int(incoming[1]), int(incoming[2]), int(incoming[3])),
                percentage=float(incoming[4]),
                wait=int(incoming[5]),
            )
        if incoming[0] == 'fill_downfrom' and len(incoming) == 6:
            # fill_upto(self, color, percentage, wait):
            self.fill_downfrom(
                (int(incoming[1]), int(incoming[2]), int(incoming[3])),
                percentage=float(incoming[4]),
                wait=int(incoming[5]),
            )
        self.stop = False


# LED system needs to be root, so need to
# create a socket based command system
# TODO @sassanh: make the socket write permission group based
# this way, apps can be set to be in LED group for permission to control
# the LEDs
if __name__ == '__main__':
    lm = LEDManager()
    lm.incoming = 'spinning_wheel 255 255 255 50 6 100'.split()
    t = Thread(target=lm.run_command, args=(lm.incoming,))
    t.start()

    uid = pwd.getpwnam('root').pw_uid
    gid = grp.getgrnam(USERNAME).gr_gid

    LM_SOCKET_PATH.unlink(missing_ok=True)

    logger.info('LED Manager opening socket...')
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(LM_SOCKET_PATH.as_posix())
    permission = (
        stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWUSR
    )
    LM_SOCKET_PATH.chmod(permission)
    # this is changing the group to pi
    # it makes sense to make a dedicated rgb-ring group
    # and add pi as user to that group
    os.chown(LM_SOCKET_PATH, uid, gid)

    logger.info('LED Manager Listening...')
    while True:
        try:
            datagram = server.recv(1024)
            if not datagram:
                break
            else:
                incoming_str = datagram.decode('utf-8')
                logger.debug(incoming_str)
                incoming = incoming_str.split()
                # set brightness of LEDs
                if incoming[0] == 'set_brightness':
                    if len(incoming) == 2:
                        brightness_value = float(incoming[1])
                        if 0 < brightness_value <= 1:
                            lm.set_brightness(brightness_value)
                else:
                    lm.stop = True
                    while t.is_alive():
                        time.sleep(0.1)
                    # save some data before overriding the object
                    logger.debug('---starting new led thread--')
                    t = Thread(target=lm.run_command, args=(incoming,))
                    t.start()
        except KeyboardInterrupt:
            logger.debug('Interrupted')
            server.close()
            try:
                sys.exit(0)
            except SystemExit:
                os._exit(0)
    logger.info('Shutting down...')
    server.close()
    LM_SOCKET_PATH.unlink()
