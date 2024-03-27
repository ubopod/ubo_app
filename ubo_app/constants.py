# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os
from distutils.util import strtobool
from pathlib import Path

import dotenv

dotenv.load_dotenv(Path(__file__).parent / '.env')

USERNAME = os.environ.get('UBO_USERNAME', 'ubo')
INSTALLATION_PATH = os.environ.get('UBO_INSTALLATION_PATH', '/opt/ubo')
DEBUG_MODE = strtobool(os.environ.get('UBO_DEBUG', 'False')) == 1
LOG_LEVEL = os.environ.get('UBO_LOG_LEVEL', 'DEBUG' if DEBUG_MODE else None)
GUI_LOG_LEVEL = os.environ.get('UBO_GUI_LOG_LEVEL', 'DEBUG' if DEBUG_MODE else None)
SERVICES_PATH = (
    os.environ.get('UBO_SERVICES_PATH', '').split(':')
    if os.environ.get('UBO_SERVICES_PATH')
    else []
)
SOCKET_PATH = Path('/run/ubo').joinpath('system_manager.sock').as_posix()

DEBUG_MODE_DOCKER = strtobool(os.environ.get('UBO_DEBUG_DOCKER', 'False')) == 1
DOCKER_PREFIX = os.environ.get('UBO_DOCKER_PREFIX', '')
DOCKER_INSTALLATION_LOCK_FILE = Path('/var/run/ubo/docker_installation.lock')

SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
