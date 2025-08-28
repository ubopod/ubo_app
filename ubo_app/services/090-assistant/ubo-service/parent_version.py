"""Get the version of the parent package using hatch."""

import os
import subprocess
from pathlib import Path


def get_version() -> str:
    """Return the version of the parent package."""
    if os.environ.get('PRETEND_VERSION'):
        return os.environ['PRETEND_VERSION']
    root = Path().absolute().parent
    while not any(i.name == 'pyproject.toml' for i in root.iterdir()):
        root = root.parent
    result = subprocess.run(
        [
            '/usr/bin/env',
            'uvx',
            '--with',
            'hatch-vcs',
            'hatch',
            'version',
        ],
        check=True,
        text=True,
        cwd=root,
        capture_output=True,
    )
    return result.stdout.strip()
