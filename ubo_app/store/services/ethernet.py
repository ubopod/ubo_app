# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from enum import StrEnum


class NetState(StrEnum):
    CONNECTED = 'Connected'
    DISCONNECTED = 'Disconnected'
    PENDING = 'Pending'
    NEEDS_ATTENTION = 'Needs Attention'
    UNKNOWN = 'Unknown'
