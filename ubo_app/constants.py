# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os
from distutils.util import strtobool
from pathlib import Path

import dotenv
import platformdirs

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
SERVER_SOCKET_PATH = Path('/run/ubo').joinpath('system_manager.sock').as_posix()
DISABLED_SERVICES = os.environ.get('UBO_DISABLED_SERVICES', '').split(',')

STORE_GRACE_TIME = int(os.environ.get('UBO_STORE_GRACE_TIME', 1))

# Enable it to replace UUIDs with numerical counters in tests and log the traceback
# each time a UUID is generated.
DEBUG_MODE_TEST_UUID = strtobool(os.environ.get('UBO_DEBUG_TEST_UUID', 'False')) == 1

PICOVOICE_ACCESS_KEY = 'PICOVOICE_ACCESS_KEY'
DOCKER_CREDENTIALS_TEMPLATE = 'DOCKER_CREDENTIALS_{}'

DEBUG_MODE_DOCKER = strtobool(os.environ.get('UBO_DEBUG_DOCKER', 'False')) == 1
DOCKER_PREFIX = os.environ.get('UBO_DOCKER_PREFIX', '')
DOCKER_INSTALLATION_LOCK_FILE = Path('/var/run/ubo/docker_installation.lock')

CONFIG_PATH = platformdirs.user_config_path(appname='ubo', ensure_exists=True)
SECRETS_PATH = CONFIG_PATH / '.secrets.env'
PERSISTENT_STORE_PATH = CONFIG_PATH / 'state.json'
