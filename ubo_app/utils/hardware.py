# pyright: reportMissingModuleSource=false
# ruff: noqa: D100, D101, D102, D103, D104, D107

from ubo_app.utils import IS_RPI


def initialize_board() -> None:
    import ubo_app.display as _  # noqa: F401

    if not IS_RPI:
        return

    from RPi import GPIO

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


def deinitalize_board() -> None:
    from ubo_app.display import display

    display.turn_off()

    if not IS_RPI:
        return

    from gpiozero.devices import _shutdown

    _shutdown()

    from RPi import GPIO

    GPIO.cleanup(17)
