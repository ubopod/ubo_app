# pyright: reportMissingModuleSource=false
# ruff: noqa: D100, D101, D102, D103, D104, D107
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
    from ubo_app.display import display

    GPIO.setup(26, GPIO.OUT)
    GPIO.output(26, GPIO.LOW)

    if not display:
        return
    data = [0] * WIDTH * HEIGHT * BYTES_PER_PIXEL
    display._block(0, 0, WIDTH - 1, HEIGHT - 1, data)  # noqa: SLF001


def turn_on_screen() -> None:
    if not IS_RPI:
        return

    from RPi import GPIO

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(26, GPIO.OUT)
    GPIO.output(26, GPIO.HIGH)
