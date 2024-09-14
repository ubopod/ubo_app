"""Sets up the display for the Raspberry Pi and manages its state."""

from __future__ import annotations

import atexit

from ubo_app import display
from ubo_app.utils import IS_RPI

splash_screen = None


def turn_off() -> None:
    """Destroy the display."""
    if IS_RPI:
        from RPi import GPIO  # pyright: ignore [reportMissingModuleSource]

        display.render_blank()

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(26, GPIO.OUT)
        GPIO.output(26, GPIO.LOW)
        GPIO.cleanup(26)


def init_service() -> None:
    """Initialize the display service."""
    if IS_RPI:
        from RPi import GPIO  # pyright: ignore [reportMissingModuleSource]

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(26, GPIO.OUT)
        GPIO.output(26, GPIO.HIGH)

        display.render_blank()

    atexit.register(turn_off)
