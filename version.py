# ruff: noqa: D100, D103
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import hatch_vcs.version_source


def get_version() -> str:
    if os.environ.get('PRETEND_VERSION'):
        return os.environ['PRETEND_VERSION']
    version_source = hatch_vcs.version_source.VCSVersionSource(Path(), {})
    vcs_version = version_source.get_version_data()['version']

    date_string = datetime.now(UTC).strftime('%y%m%d')

    return re.sub(
        r'\+(.*)(?:\.d.*)?$',
        lambda m: date_string + ''.join(str(ord(c)) for c in m.group(1))[:11],
        vcs_version,
    )
