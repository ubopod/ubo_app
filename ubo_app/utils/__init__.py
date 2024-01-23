# ruff: noqa: D100, D101, D102, D103, D104, D107
from pathlib import Path

from headless_kivy_pi.constants import BYTES_PER_PIXEL

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

    from headless_kivy_pi import HeadlessWidget

    display = HeadlessWidget._display  # noqa: SLF001
    data = [0] * HeadlessWidget.width * HeadlessWidget.height * BYTES_PER_PIXEL
    display._block(0, 0, HeadlessWidget.width - 1, HeadlessWidget.height - 1, data)  # noqa: SLF001


def turn_on_screen() -> None:
    if not IS_RPI:
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(26, GPIO.OUT)
    GPIO.output(26, GPIO.HIGH)
