# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os
from distutils.util import strtobool

DEBUG_MODE = strtobool(os.environ.get('UBO_DEBUG', 'False')) == 1
SERVICES_PATH = (
    os.environ.get('UBO_SERVICES_PATH', '').split(':')
    if os.environ.get('UBO_SERVICES_PATH')
    else []
)
