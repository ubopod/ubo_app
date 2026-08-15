"""Pure text-shaping for the Docker logs view.

Separate from ``docker_logs`` so it can be imported — and tested — without
standing up the store or the docker client. The size ceiling here is what keeps
a log tail from reaching an MCU client that cannot hold it, so it is worth
testing directly rather than only through a running pod.
"""

from __future__ import annotations

import re

# How much log to carry. `LOG_TEXT_LIMIT` is the one that actually protects the
# MCU clients; the line and length caps just keep the common case well under it.
LOG_TAIL_LINES = 25
LOG_LINE_LIMIT = 100
LOG_TEXT_LIMIT = 2**11  # 2 KiB, same ceiling as the file viewer.

PLACEHOLDER = 'No logs yet.'

# Containers colorize freely and nothing downstream interprets ANSI: Kivy, LVGL
# and the web viewer would all render the escape bytes as literal garbage.
_ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')

_ELISION = '…\n'


def format_logs(raw: str) -> str:
    """Trim a raw log dump down to what may cross the wire.

    Truncation keeps the *end* — the opposite of the file viewer, which keeps
    the head. A log's diagnostic value is entirely in its most recent lines.
    """
    lines = [
        line[:LOG_LINE_LIMIT]
        for line in _ANSI.sub('', raw).replace('\r\n', '\n').split('\n')
    ]
    text = '\n'.join(lines[-LOG_TAIL_LINES:]).strip()

    encoded = text.encode('utf-8')
    if len(encoded) > LOG_TEXT_LIMIT:
        # Slicing bytes can land mid-codepoint; `ignore` drops the partial head
        # rather than raising on it.
        text = _ELISION + encoded[-LOG_TEXT_LIMIT:].decode('utf-8', errors='ignore')
    return text
