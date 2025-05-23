# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os
from pathlib import Path

import platformdirs
from str_to_bool import str_to_bool

if __package__ is None:
    msg = 'The package name is not set.'
    raise ValueError(msg)
PACKAGE_NAME = __package__
USERNAME = os.environ.get('UBO_USERNAME', 'ubo')
INSTALLATION_PATH = os.environ.get('UBO_INSTALLATION_PATH', '/opt/ubo')

DEBUG_VISUAL = str_to_bool(os.environ.get('UBO_DEBUG_VISUAL', 'False'))
DEBUG_BETA_VERSIONS = str_to_bool(os.environ.get('UBO_DEBUG_BETA_VERSIONS', 'False'))
DEBUG_PDB_SIGNAL = str_to_bool(os.environ.get('UBO_DEBUG_PDB_SIGNAL', 'False'))
DEBUG_TASKS = str_to_bool(os.environ.get('UBO_DEBUG_TASKS', 'False'))
DEBUG_DOCKER = str_to_bool(os.environ.get('UBO_DEBUG_DOCKER', 'False'))
DEBUG_TEST_UUID = str_to_bool(os.environ.get('UBO_DEBUG_TEST_UUID', 'False'))
DEBUG_MENU = str_to_bool(os.environ.get('UBO_DEBUG_MENU', 'False'))

LOG_LEVEL = os.environ.get('UBO_LOG_LEVEL', 'INFO')
GUI_LOG_LEVEL = os.environ.get('UBO_GUI_LOG_LEVEL', 'INFO')
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

DISABLE_GRPC = str_to_bool(os.environ.get('UBO_DISABLE_GRPC', 'False'))
GRPC_LISTEN_ADDRESS = os.environ.get('UBO_GRPC_LISTEN_ADDRESS', '127.0.0.1')
GRPC_LISTEN_PORT = int(os.environ.get('UBO_GRPC_LISTEN_PORT', '50051'))

GRPC_ENVOY_LISTEN_ADDRESS = os.environ.get('UBO_GRPC_ENVOY_LISTEN_ADDRESS', '0.0.0.0')  # noqa: S104
GRPC_ENVOY_LISTEN_PORT = int(os.environ.get('UBO_GRPC_ENVOY_LISTEN_PORT', '50052'))

# Most of these should be changed in ubo-app and ubo-system-manager simultaneously to
# avoid breaking the system.
# TODO(sassanh): Make above comment visible to the end user when a change # noqa: FIX002
# is detected in of these values.
WEB_UI_LISTEN_ADDRESS = os.environ.get('UBO_WEB_UI_LISTEN_ADDRESS', '0.0.0.0')  # noqa: S104
WEB_UI_LISTEN_PORT = int(os.environ.get('UBO_WEB_UI_LISTEN_PORT', '4321'))
WEB_UI_DEBUG_MODE = str_to_bool(os.environ.get('UBO_WEB_UI_DEBUG_MODE', 'False'))
WEB_UI_HOTSPOT_PASSWORD = os.environ.get('UBO_WEB_UI_HOTSPOT_PASSWORD', 'ubopod-setup')

UPDATE_ASSETS_PATH = Path(f'{INSTALLATION_PATH}/_update/')

SERVICES_LOOP_GRACE_PERIOD = float(
    os.environ.get('UBO_SERVICES_LOOP_GRACE_PERIOD', '0.1'),
)
MAIN_LOOP_GRACE_PERIOD = int(os.environ.get('UBO_MAIN_LOOP_GRACE_PERIOD', '1'))
STORE_GRACE_PERIOD = int(os.environ.get('UBO_STORE_GRACE_PERIOD', '1'))

# Enable it to replace UUIDs with numerical counters in tests and log the traceback
# each time a UUID is generated.

PICOVOICE_ACCESS_KEY = 'PICOVOICE_ACCESS_KEY'

DOCKER_CREDENTIALS_TEMPLATE = 'DOCKER_CREDENTIALS_{}'

CONFIG_PATH = platformdirs.user_config_path(appname='ubo', ensure_exists=True)
SECRETS_PATH = CONFIG_PATH / '.secrets.env'
PERSISTENT_STORE_PATH = CONFIG_PATH / 'state.json'

CACHE_PATH = Path(
    os.environ.get(
        'UBO_CACHE_PATH',
        platformdirs.user_cache_path(appname='ubo', ensure_exists=True),
    ),
)
DATA_PATH = Path(
    os.environ.get(
        'UBO_DATA_PATH',
        platformdirs.user_data_path(appname='ubo', ensure_exists=True),
    ),
)

DISPLAY_BAUDRATE = int(os.environ.get('UBO_DISPLAY_BAUDRATE', '60_000_000'))
WIDTH = 240
HEIGHT = 240
BYTES_PER_PIXEL = 2

NOTIFICATIONS_FLASH_TIME = 4


CORE_SERVICE_IDS = [
    'assistant',
    'audio',
    'camera',
    'display',
    'docker',
    'ethernet',
    'file_system',
    'infrared',
    'ip',
    'keyboard',
    'keypad',
    'lightdm',
    'notifications',
    'rgb_ring',
    'rpi_connect',
    'sensors',
    'speech_recognition',
    'speech_synthesis',
    'ssh',
    'users',
    'vscode',
    'web_ui',
    'wifi',
]

TEST_INVESTIGATION_MODE = str_to_bool(
    os.environ.get('UBO_TEST_INVESTIGATION_MODE', 'False'),
)

WAKE_WORD = os.environ.get('UBO_WAKE_WORD', 'hey pod')
ASSISTANT_WAKE_WORD = os.environ.get('UBO_ASSISTANT_WAKE_WORD', 'hey there')
ASSISTANT_END_WORD = os.environ.get('UBO_ASSISTANT_END_WORD', 'roger that')
ASSISTANT_DEBUG_PATH = os.environ.get('UBO_ASSISTANT_DEBUG_PATH')
DEFAULT_ASSISTANT_OLLAMA_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OLLAMA_MODEL',
    'gemma3:1b',
)
