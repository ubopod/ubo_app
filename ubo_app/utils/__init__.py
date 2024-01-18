# ruff: noqa: D100, D101, D102, D103, D104, D107
from pathlib import Path

IS_RPI = Path('/etc/rpi-issue').exists()
