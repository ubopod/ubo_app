"""Provides `IS_RPI` and `IS_TEST_ENV` constants."""

import contextlib
import sys
from pathlib import Path

IS_RPI = Path('/etc/rpi-issue').exists()
IS_RPI_4 = False
with contextlib.suppress(Exception):
    IS_RPI_4 = IS_RPI and Path('/proc/device-tree/model').read_text().startswith(
        'Raspberry Pi 4',
    )
IS_TEST_ENV = any('pytest' in arg.lower() for arg in sys.argv)

from ubo_app.utils.eeprom import (  # noqa: E402
    UNAVAILABLE_SERIAL_NUMBER,
    read_serial_number,
)

IS_UBO_POD = read_serial_number() is not UNAVAILABLE_SERIAL_NUMBER
