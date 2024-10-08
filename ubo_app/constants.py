# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os
from pathlib import Path

import platformdirs
from str_to_bool import str_to_bool

USERNAME = os.environ.get('UBO_USERNAME', 'ubo')
INSTALLER_URL = os.environ.get(
    'UBO_INSTALLER_URL',
    'https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/install.sh',
)
INSTALLATION_PATH = os.environ.get('UBO_INSTALLATION_PATH', '/opt/ubo')
DEBUG_MODE = str_to_bool(os.environ.get('UBO_DEBUG', 'False')) == 1
DEBUG_MODE_TASKS = str_to_bool(os.environ.get('UBO_DEBUG_TASKS', 'False')) == 1
LOG_LEVEL = os.environ.get('UBO_LOG_LEVEL', 'DEBUG' if DEBUG_MODE else None)
GUI_LOG_LEVEL = os.environ.get('UBO_GUI_LOG_LEVEL', 'DEBUG' if DEBUG_MODE else None)
SERVICES_PATH = (
    os.environ.get('UBO_SERVICES_PATH', '').split(':')
    if os.environ.get('UBO_SERVICES_PATH')
    else []
)
SERVER_SOCKET_PATH = Path('/run/ubo').joinpath('system_manager.sock').as_posix()
DISABLED_SERVICES = os.environ.get('UBO_DISABLED_SERVICES', '')
DISABLED_SERVICES = DISABLED_SERVICES.split(',') if DISABLED_SERVICES else []
ENABLED_SERVICES = os.environ.get('UBO_ENABLED_SERVICES', '')
ENABLED_SERVICES = ENABLED_SERVICES.split(',') if ENABLED_SERVICES else []

DISABLE_GRPC = str_to_bool(os.environ.get('UBO_DISABLE_GRPC', 'False')) == 1
GRPC_LISTEN_HOST = os.environ.get('UBO_GRPC_LISTEN_HOST', '127.0.0.1')
GRPC_LISTEN_PORT = int(os.environ.get('UBO_GRPC_LISTEN_PORT', '50051'))

WEB_UI_LISTEN_HOST = os.environ.get('UBO_WEB_UI_LISTEN_HOST', '0.0.0.0')  # noqa: S104
WEB_UI_LISTEN_PORT = int(os.environ.get('UBO_WEB_UI_LISTEN_PORT', '21215'))
WEB_UI_DEBUG_MODE = str_to_bool(os.environ.get('UBO_WEB_UI_DEBUG_MODE', 'False')) == 1

UPDATE_ASSETS_PATH = Path(f'{INSTALLATION_PATH}/_update/')
UPDATE_LOCK_PATH = UPDATE_ASSETS_PATH / 'update_is_ready.lock'

DEBUG_MODE_MENU = str_to_bool(os.environ.get('UBO_DEBUG_MENU', 'False')) == 1

SERVICES_LOOP_GRACE_PERIOD = float(
    os.environ.get('UBO_SERVICES_LOOP_GRACE_PERIOD', 0.1),
)
MAIN_LOOP_GRACE_PERIOD = int(os.environ.get('UBO_MAIN_LOOP_GRACE_PERIOD', 1))
STORE_GRACE_PERIOD = int(os.environ.get('UBO_STORE_GRACE_PERIOD', 1))

# Enable it to replace UUIDs with numerical counters in tests and log the traceback
# each time a UUID is generated.
DEBUG_MODE_TEST_UUID = str_to_bool(os.environ.get('UBO_DEBUG_TEST_UUID', 'False')) == 1

PICOVOICE_ACCESS_KEY = 'PICOVOICE_ACCESS_KEY'

DEBUG_MODE_DOCKER = str_to_bool(os.environ.get('UBO_DEBUG_DOCKER', 'False')) == 1
DOCKER_CREDENTIALS_TEMPLATE = 'DOCKER_CREDENTIALS_{}'
DOCKER_PREFIX = os.environ.get('UBO_DOCKER_PREFIX', '')

CONFIG_PATH = platformdirs.user_config_path(appname='ubo', ensure_exists=True)
SECRETS_PATH = CONFIG_PATH / '.secrets.env'
PERSISTENT_STORE_PATH = CONFIG_PATH / 'state.json'

WIDTH = 240
HEIGHT = 240
BYTES_PER_PIXEL = 2

NOTIFICATIONS_FLASH_TIME = 4
