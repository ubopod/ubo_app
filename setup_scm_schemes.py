from setuptools_scm.version import get_local_node_and_date # pyright: ignore
import re
from datetime import datetime, timezone


def local_scheme(version):
    version.node = re.sub(
        r'.',
        lambda match: str(ord(match.group(0))),
        version.node
    )
    original_local_version = get_local_node_and_date(version)
    numeric_version = original_local_version.replace('+', '').replace('.d', '')
    return datetime.now(timezone.utc).strftime('%y%m%d') + numeric_version
