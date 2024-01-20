# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from enum import StrEnum
from typing import Sequence

from redux import BaseAction, BaseEvent, Immutable


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


class WiFiAction(BaseAction):
    ...


class WiFiUpdateAction(WiFiAction):
    connections: Sequence[WiFiConnection]
    state: GlobalWiFiState
    current_connection: WiFiConnection | None


class WiFiUpdateRequestAction(WiFiAction):
    reset: bool = False


class WiFiEvent(BaseEvent):
    ...


class WiFiCreateEvent(WiFiEvent):
    connection: WiFiConnection


class WiFiUpdateRequestEvent(WiFiEvent):
    ...


class WiFiState(Immutable):
    connections: Sequence[WiFiConnection] | None
    state: GlobalWiFiState
    current_connection: WiFiConnection | None
