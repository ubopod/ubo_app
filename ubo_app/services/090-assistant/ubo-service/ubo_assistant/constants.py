"""Project constants."""

import os
from pathlib import Path

import platformdirs

IS_RPI = Path('/etc/rpi-issue').exists()
DATA_PATH = Path(
    os.environ.get(
        'UBO_DATA_PATH',
        platformdirs.user_data_path(appname='ubo', ensure_exists=True),
    ),
)
