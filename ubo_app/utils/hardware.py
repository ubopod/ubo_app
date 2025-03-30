# pyright: reportMissingModuleSource=false
# ruff: noqa: D100, D101, D102, D103, D104, D107

from ubo_app.utils import IS_RPI


def initialize_board() -> None:
    # Display will be initialized in the display module after importing it
    import ubo_app.display as _  # noqa: F401


def deinitalize_board() -> None:
    from ubo_app.display import display

    display.turn_off()

    if not IS_RPI:
        return

    from gpiozero.devices import _shutdown

    _shutdown()
