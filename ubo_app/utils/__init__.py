# ruff: noqa: D100, D101, D102, D103, D104, D107
import os
from pathlib import Path

IS_RPI = Path('/etc/rpi-issue').exists()
IS_TEST_ENV = 'PYTEST_CURRENT_TEST' in os.environ
