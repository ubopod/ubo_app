# ruff: noqa: D104, N999
from pathlib import Path

IS_RPI = Path('/etc/rpi-issue').exists()
if IS_RPI:
    from . import rpi_keypad
