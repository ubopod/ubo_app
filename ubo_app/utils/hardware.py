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
    import headless_kivy_pi.config
    from headless_kivy_pi.constants import BYTES_PER_PIXEL
    from RPi import GPIO

    GPIO.setup(26, GPIO.OUT)
    GPIO.output(26, GPIO.LOW)

    display = headless_kivy_pi.config._display  # noqa: SLF001
    if not display:
        return
    data = (
        [0]
        * headless_kivy_pi.config.width()
        * headless_kivy_pi.config.height()
        * BYTES_PER_PIXEL
    )
    display._block(  # noqa: SLF001
        0,
        0,
        headless_kivy_pi.config.width() - 1,
        headless_kivy_pi.config.height() - 1,
        data,
    )


def turn_on_screen() -> None:
    if not IS_RPI:
        return

    from RPi import GPIO

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(26, GPIO.OUT)
    GPIO.output(26, GPIO.HIGH)
