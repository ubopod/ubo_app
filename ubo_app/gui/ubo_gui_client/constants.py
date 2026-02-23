"""Constants for the GUI client."""

from __future__ import annotations

import os
import platform

from str_to_bool import str_to_bool

IS_RPI = platform.machine() == 'aarch64'
IS_TEST_ENV = str_to_bool(os.environ.get('UBO_TEST_ENV', 'False'))
DEBUG_MENU = str_to_bool(os.environ.get('UBO_DEBUG_MENU', 'False'))

DISPLAY_BAUDRATE = int(os.environ.get('UBO_DISPLAY_BAUDRATE', '60_000_000'))
WIDTH = 240
HEIGHT = 240
BYTES_PER_PIXEL = 2

PAGE_SIZE = 3

# Color constants (from ubo_gui.constants)
INFO_COLOR = '#2196F3'
SUCCESS_COLOR = '#03F7AE'
