"""Constants of the ubo app."""

import os
from pathlib import Path

import platformdirs
from str_to_bool import str_to_bool

if __package__ is None:
    msg = 'The package name is not set.'
    raise ValueError(msg)
PACKAGE_NAME = __package__.rpartition('.')[0]
USERNAME = os.environ.get('UBO_USERNAME', 'ubo')
INSTALLATION_PATH = os.environ.get('UBO_INSTALLATION_PATH', '/opt/ubo')

FORCE_HARDWARE = str_to_bool(os.environ.get('UBO_FORCE_HARDWARE', 'False'))

DEBUG_VISUAL = str_to_bool(os.environ.get('UBO_DEBUG_VISUAL', 'False'))
DEBUG_BETA_VERSIONS = str_to_bool(os.environ.get('UBO_DEBUG_BETA_VERSIONS', 'False'))
DEBUG_PDB_SIGNAL = str_to_bool(os.environ.get('UBO_DEBUG_PDB_SIGNAL', 'False'))
DEBUG_TASKS = str_to_bool(os.environ.get('UBO_DEBUG_TASKS', 'False'))
DEBUG_DOCKER = str_to_bool(os.environ.get('UBO_DEBUG_DOCKER', 'False'))
DEBUG_TEST_UUID = str_to_bool(os.environ.get('UBO_DEBUG_TEST_UUID', 'False'))
DEBUG_MENU = str_to_bool(os.environ.get('UBO_DEBUG_MENU', 'False'))
DEBUG_SCHEDULER = str_to_bool(os.environ.get('UBO_DEBUG_SCHEDULER', 'False'))
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

# Port of the Envoy raw TCP-proxy listener that forwards native gRPC traffic to
# the loopback-only core server, exposing it to the LAN when the user enables the
# "gRPC Access" setting. See ubo_app/services/080-docker/apps/envoy.py.
GRPC_NATIVE_PROXY_LISTEN_PORT = int(
    os.environ.get('UBO_GRPC_NATIVE_PROXY_LISTEN_PORT', '50053'),
)

# Lightweight raw-TCP listener ("tcp-lite") for MCU/ESP32 clients — a second,
# parallel transport alongside the grpclib/Envoy path, carrying only
# DispatchAction/SubscribeStore/SubscribeEvent. Bound to the LAN in-process
# (like MCP_GATEWAY_LISTEN_ADDRESS) so the device reaches it directly. Port
# 50054 avoids the 50051/50052/50053/4321/4322 range. See ubo_app/rpc/mcu_server.py.
DISABLE_MCU_SERVER = str_to_bool(os.environ.get('UBO_DISABLE_MCU_SERVER', 'False'))
MCU_LISTEN_ADDRESS = os.environ.get('UBO_MCU_LISTEN_ADDRESS', '0.0.0.0')  # noqa: S104
MCU_LISTEN_PORT = int(os.environ.get('UBO_MCU_LISTEN_PORT', '50054'))

# Most of these should be changed in ubo-app and ubo-system-manager simultaneously to
# avoid breaking the system.
# TODO(sassanh): Make above comment visible to the end user when a change # noqa: FIX002
# is detected in of these values.
WEB_UI_LISTEN_ADDRESS = os.environ.get('UBO_WEB_UI_LISTEN_ADDRESS', '0.0.0.0')  # noqa: S104
WEB_UI_LISTEN_PORT = int(os.environ.get('UBO_WEB_UI_LISTEN_PORT', '4321'))
WEB_UI_DEBUG_MODE = str_to_bool(os.environ.get('UBO_WEB_UI_DEBUG_MODE', 'False'))
WEB_UI_HOTSPOT_PASSWORD = os.environ.get('UBO_WEB_UI_HOTSPOT_PASSWORD', 'ubopod-setup')

# MCP gateway — the in-tree FastMCP proxy aggregates every enabled MCP server
# behind a single token-gated endpoint (``/sse`` + ``/mcp``). Bound to the LAN so
# off-device clients (Claude Desktop, hermes, OpenCLAW) can reach it; the
# assistant subprocess connects to it over localhost.
MCP_GATEWAY_LISTEN_ADDRESS = os.environ.get('UBO_MCP_GATEWAY_LISTEN_ADDRESS', '0.0.0.0')  # noqa: S104
MCP_GATEWAY_LISTEN_PORT = int(os.environ.get('UBO_MCP_GATEWAY_LISTEN_PORT', '4322'))
# Bearer token the gateway requires; shared with the assistant subprocess so it
# can authenticate to the local gateway with the same token.
MCP_GATEWAY_TOKEN_SECRET_ID = 'mcp_gateway_token'  # noqa: S105

UPDATE_ASSETS_PATH = Path(f'{INSTALLATION_PATH}/_update/')

SERVICES_LOOP_GRACE_PERIOD = float(
    os.environ.get('UBO_SERVICES_LOOP_GRACE_PERIOD', '0.1'),
)
SUBPROCESS_TERMINATE_GRACE_PERIOD = float(
    os.environ.get('UBO_SUBPROCESS_TERMINATE_GRACE_PERIOD', '5.0'),
)
MAIN_LOOP_GRACE_PERIOD = int(os.environ.get('UBO_MAIN_LOOP_GRACE_PERIOD', '1'))
STORE_GRACE_PERIOD = int(os.environ.get('UBO_STORE_GRACE_PERIOD', '1'))

# Enable it to replace UUIDs with numerical counters in tests and log the traceback
# each time a UUID is generated.

DOCKER_CREDENTIALS_TEMPLATE_SECRET_ID = 'docker_credentials:{}'  # noqa: S105

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
# `ensure_exists` above only applies to the platformdirs default; an
# UBO_DATA_PATH override (e.g. tests/.env) bypasses it, so guarantee the
# directory exists unconditionally — service_thread.py spawns binaries with
# cwd=DATA_PATH, and a missing cwd fails create_subprocess_exec outright.
DATA_PATH.mkdir(parents=True, exist_ok=True)

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
    'kiosk',
    'lightdm',
    'mcp',
    'mqtt',
    'notifications',
    'rgb_ring',
    'rpi_connect',
    'sensors',
    'speech_recognition',
    'speech_synthesis',
    'ssh',
    'system',
    'users',
    'vscode',
    'web_ui',
    'wifi',
]

TEST_INVESTIGATION_MODE = str_to_bool(
    os.environ.get('UBO_TEST_INVESTIGATION_MODE', 'False'),
)

SPEECH_RECOGNITION_FRAME_RATE = 16_000
SPEECH_RECOGNITION_SAMPLE_WIDTH = 2

DISPLAY_BLANK_TIMEOUT = 15.0  # seconds
