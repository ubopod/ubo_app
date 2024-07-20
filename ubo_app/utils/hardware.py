# pyright: reportMissingModuleSource=false
# ruff: noqa: D100, D101, D102, D103, D104, D107

from ubo_app.utils import IS_RPI


def initialize_board() -> None:
    if not IS_RPI:
        return

    from RPi import GPIO

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
