# pyright: reportMissingModuleSource=false
# ruff: noqa: D100, D101, D102, D103, D104, D107
import numpy as np

from ubo_app.utils import IS_RPI


def initialize_board() -> None:
    if not IS_RPI:
        return

    from RPi import GPIO

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


def turn_off_screen() -> None:
    if not IS_RPI:
        return
    from RPi import GPIO

    from ubo_app.constants import BYTES_PER_PIXEL, HEIGHT, WIDTH
    from ubo_app.display import state

    GPIO.setup(26, GPIO.OUT)
    GPIO.output(26, GPIO.LOW)

    data = np.zeros((WIDTH, HEIGHT, BYTES_PER_PIXEL), dtype=np.uint8)
    state.block((0, 0, WIDTH - 1, HEIGHT - 1), data.tobytes())


def turn_on_screen() -> None:
    if not IS_RPI:
        return

    from RPi import GPIO

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(26, GPIO.OUT)
    GPIO.output(26, GPIO.HIGH)
