# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store

if TYPE_CHECKING:
    from collections.abc import Sequence


class WiFiType(StrEnum):
    WEP = 'WEP'
    WPA = 'WPA'
    WPA2 = 'WPA2'
    nopass = 'NOPASS'


class ConnectionState(StrEnum):
    CONNECTED = 'Connected'
    CONNECTING = 'Connecting'
    DISCONNECTED = 'Disconnected'
    UNKNOWN = 'Unknown'


class GlobalWiFiState(StrEnum):
    CONNECTED = 'Connected'
    DISCONNECTED = 'Disconnected'
    PENDING = 'Pending'
    NEEDS_ATTENTION = 'Needs Attention'
    UNKNOWN = 'Unknown'


class WiFiConnection(Immutable):
    ssid: str
    state: ConnectionState = ConnectionState.UNKNOWN
    signal_strength: int = 0
    password: str | None = None
    type: WiFiType | None = None
    hidden: bool = False


class WiFiAction(BaseAction): ...


class WiFiSetHasVisitedOnboardingAction(WiFiAction):
    has_visited_onboarding: bool


class WiFiUpdateAction(WiFiAction):
    connections: Sequence[WiFiConnection]
    state: GlobalWiFiState
    current_connection: WiFiConnection | None


class WiFiUpdateRequestAction(WiFiAction):
    reset: bool = False


class WiFiEvent(BaseEvent): ...


class WiFiUpdateRequestEvent(WiFiEvent): ...


class WiFiState(Immutable):
    connections: Sequence[WiFiConnection] | None
    state: GlobalWiFiState
    current_connection: WiFiConnection | None
    has_visited_onboarding: bool = field(
        default_factory=lambda: read_from_persistent_store(
            key='wifi_has_visited_onboarding',
            default=False,
        ),
    )
