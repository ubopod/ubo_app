# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os
from distutils.util import strtobool

USERNAME = 'ubo'
INSTALLATION_PATH = '/opt/ubo'
DEBUG_MODE = strtobool(os.environ.get('UBO_DEBUG', 'False')) == 1
LOG_LEVEL = os.environ.get('UBO_LOG_LEVEL', 'DEBUG' if DEBUG_MODE else None)
GUI_LOG_LEVEL = os.environ.get('UBO_GUI_LOG_LEVEL', 'DEBUG' if DEBUG_MODE else None)
SERVICES_PATH = (
    os.environ.get('UBO_SERVICES_PATH', '').split(':')
    if os.environ.get('UBO_SERVICES_PATH')
    else []
)
