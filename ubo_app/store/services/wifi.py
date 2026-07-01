# ruff: noqa: D100, D101
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


class WiFiInputConnectionAction(WiFiAction): ...


class WiFiSetHasVisitedOnboardingAction(WiFiAction):
    has_visited_onboarding: bool


class WiFiUpdateAction(WiFiAction):
    connections: Sequence[WiFiConnection]
    state: NetState
    current_connection: WiFiConnection | None


class WiFiUpdateRequestAction(WiFiAction):
    reset: bool = False


class WiFiStartHotspotAction(WiFiAction):
    """Bring up the Wi-Fi hotspot (wlan0 in AP mode).

    ``mode`` is the OS networking mode: ``'captive'`` (DNS-hijack data-entry
    portal) or ``'share'`` (NAT the clients out to the upstream uplink).
    """

    mode: str = 'captive'


class WiFiStopHotspotAction(WiFiAction):
    """Tear the Wi-Fi hotspot down and hand wlan0 back to managed mode.

    Dispatched explicitly: from the settings toggle, when the onboarding journey
    completes, or when a real network route appears - so the hotspot is never
    torn down merely because an input demand resolved.
    """


class WiFiSetHotspotRunningAction(WiFiAction):
    """Sync the tracked hotspot running state after a start/stop side effect.

    ``user_enabled`` is True only for an explicitly toggled-on hotspot; the
    route-driven auto-stop leaves those up (so an internet-sharing hotspot is not
    torn down just because the device has an upstream route).
    """

    is_running: bool
    user_enabled: bool = False


class WiFiEvent(BaseEvent): ...


class WiFiInputConnectionEvent(WiFiEvent): ...


class WiFiUpdateRequestEvent(WiFiEvent): ...


class WiFiStartHotspotEvent(WiFiEvent):
    mode: str = 'captive'


class WiFiStopHotspotEvent(WiFiEvent): ...


class WiFiState(Immutable):
    connections: Sequence[WiFiConnection] | None
    state: NetState
    current_connection: WiFiConnection | None
    has_visited_onboarding: bool | None = None
    is_hotspot_running: bool = False
    hotspot_user_enabled: bool = False
