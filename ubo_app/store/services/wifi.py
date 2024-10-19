# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.services.ethernet import NetState


class WiFiType(StrEnum):
    WEP = 'WEP'
    WPA = 'WPA'
    WPA2 = 'WPA2'
    NOPASS = 'NOPASS'


class ConnectionState(StrEnum):
    CONNECTED = 'Connected'
    CONNECTING = 'Connecting'
    DISCONNECTED = 'Disconnected'
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
    state: NetState
    current_connection: WiFiConnection | None


class WiFiUpdateRequestAction(WiFiAction):
    reset: bool = False


class WiFiEvent(BaseEvent): ...


class WiFiUpdateRequestEvent(WiFiEvent): ...


class WiFiState(Immutable):
    connections: Sequence[WiFiConnection] | None
    state: NetState
    current_connection: WiFiConnection | None
    has_visited_onboarding: bool | None = None
