import subprocess
from pathlib import Path


def get_version():
    """
    Returns the version of the parent package.
    """

    root = Path().absolute().parent
    while not any(i.name == "pyproject.toml" for i in root.iterdir()):
        root = root.parent
    result = subprocess.run(
        [
            "/usr/bin/env",
            "uvx",
            "hatch",
            "version",
        ],
        # check=True,
        text=True,
        cwd=root,
        capture_output=True,
    )
    return result.stdout.strip()
