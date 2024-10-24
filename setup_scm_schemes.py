# ruff: noqa: D100, D103
import re
from datetime import UTC, datetime

from setuptools_scm.version import (  # pyright: ignore [reportMissingImports]
    get_local_node_and_date,
)


def local_scheme(version) -> str:  # noqa: ANN001
    version.node = re.sub(r'.', lambda match: str(ord(match.group(0))), version.node)
    original_local_version = get_local_node_and_date(version)
    numeric_version = original_local_version.replace('+', '').replace('.d', '')
    return datetime.now(UTC).strftime('%y%m%d') + numeric_version
