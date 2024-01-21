# ruff: noqa: D100, D101, D102, D103, D104, D107
from pathlib import Path

from ubo_app.utils.fake import Fake

IS_RPI = Path('/etc/rpi-issue').exists()
if not IS_RPI:
    import sys

    sys.modules['RPi'] = Fake()

from RPi import GPIO  # pyright: ignore [reportMissingImports]  # noqa: E402


def initialize_board() -> None:
    if not IS_RPI:
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


def turn_off_screen() -> None:
    if not IS_RPI:
        return

    GPIO.setup(26, GPIO.OUT)
    GPIO.output(26, GPIO.LOW)


def turn_on_screen() -> None:
    if not IS_RPI:
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(26, GPIO.OUT)
    GPIO.output(26, GPIO.HIGH)
