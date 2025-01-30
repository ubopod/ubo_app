"""Set up the hotspot configuration files."""

import pathlib
import sys

from ubo_app.constants import WEB_UI_HOTSPOT_PASSWORD
from ubo_app.utils.pod_id import get_pod_id
from ubo_app.utils.template_files import copy_templates, restore_backups


def main() -> None:
    """Set up the hotspot configuration files."""
    templates_path = pathlib.Path(__file__).parent / 'hotspot_templates'
    if sys.argv[1] == 'configure':
        copy_templates(
            templates_path,
            variables={
                'SSID': get_pod_id(with_default=True),
                'PASSWORD': WEB_UI_HOTSPOT_PASSWORD,
            },
        )
    elif sys.argv[1] == 'restore':
        restore_backups(templates_path)
    else:
        msg = 'Invalid argument'
        raise ValueError(msg)
