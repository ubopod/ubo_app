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

    def make_suffix(m: re.Match[str]) -> str:
        # Use only the git hash part, exclude dirty suffix
        hash_part = m.group(1)
        ordinals = ''.join(str(ord(c)) for c in hash_part)
        # Limit total suffix to 18 digits to stay within 64-bit integer limit
        return '.dev' + (date_string + ordinals)[:18]

    # Replace entire .devN+hash(.d...)? with custom .dev<suffix>
    return re.sub(
        r'\.dev\d+\+([^.]+)(?:\.d.*)?$',
        make_suffix,
        vcs_version,
    )
