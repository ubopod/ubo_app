# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
import platform
from pathlib import Path

from ubo_app.constants import INSTALLATION_PATH


def get_cli_tool_name() -> str:  # noqa: C901
    # Determine the OS type and architecture
    os_type = platform.system().lower()
    arch = platform.machine().lower()

    if os_type == 'linux':
        if 'aarch64' in arch or 'arm64' in arch:
            return 'cli-alpine-arm64'
        if 'arm' in arch:
            return 'cli-alpine-armhf'
        if 'x86_64' in arch:
            return 'cli-alpine-x64'

    if os_type == 'darwin':
        if 'arm64' in arch:
            return 'cli-darwin-arm64'
        if 'x86_64' in arch:
            return 'cli-darwin-x64'

    if os_type == 'windows':
        if 'arm64' in arch:
            return 'cli-win32-arm64'
        if 'x86_64' in arch:
            return 'cli-win32-x64'
        if 'x86' in arch:
            return 'cli-win32'

    raise ValueError


CODE_BINARY_URL = (
    f'https://code.visualstudio.com/sha/download?build=stable&os={get_cli_tool_name()}'
)

CODE_BINARY_PATH = Path(INSTALLATION_PATH) / 'code'
DOWNLOAD_PATH = CODE_BINARY_PATH.parent / 'code.tar.gz'
