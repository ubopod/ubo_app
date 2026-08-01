"""State and actions for the Home Assistant Wyoming integration."""

from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from ipaddress import ip_address, ip_network
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store

if TYPE_CHECKING:
    from collections.abc import Iterable


class WyomingConnectionPolicy(StrEnum):
    """Network locations allowed to open a Wyoming connection."""

    LOCAL_ONLY = 'local-only'
    DOCKER_HOME_ASSISTANT = 'docker-home-assistant'
    ALLOWLIST = 'allowlist'


class WyomingSatelliteStatus(StrEnum):
    """Runtime state of the satellite listener."""

    STOPPED = 'stopped'
    LISTENING = 'listening'
    CONNECTED = 'connected'
    STREAMING = 'streaming'
    PLAYING = 'playing'
    PAUSED = 'paused'


class WyomingEnginesStatus(StrEnum):
    """Runtime state of the ASR, TTS, and handle listener."""

    STOPPED = 'stopped'
    LISTENING = 'listening'
    BUSY = 'busy'


def normalize_allowed_peers(peers: Iterable[object]) -> tuple[str, ...]:
    """Return canonical IP/CIDR peers, rejecting hostnames and malformed values."""
    normalized: set[str] = set()
    for peer in peers:
        if not isinstance(peer, str):
            continue
        try:
            stripped = peer.strip()
            normalized_peer = (
                str(ip_network(stripped, strict=False))
                if '/' in stripped
                else str(ip_address(stripped))
            )
        except ValueError:
            continue
        normalized.add(normalized_peer)
    return tuple(sorted(normalized))


def _load_connection_policy(value: object) -> WyomingConnectionPolicy:
    """Load an older or malformed persistent value without broadening access."""
    if isinstance(value, str):
        try:
            return WyomingConnectionPolicy(value)
        except ValueError:
            pass
    return WyomingConnectionPolicy.LOCAL_ONLY


def _load_allowed_peers(value: object) -> tuple[str, ...]:
    """Load only a collection of valid IP network values from persistence."""
    if isinstance(value, list | tuple):
        return normalize_allowed_peers(value)
    return ()


class WyomingState(Immutable):
    """Persisted configuration and serializable runtime status."""

    is_satellite_enabled: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'wyoming:is_satellite_enabled',
            default=False,
        ),
    )
    is_engines_enabled: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'wyoming:is_engines_enabled',
            default=False,
        ),
    )
    connection_policy: WyomingConnectionPolicy = field(
        default_factory=lambda: read_from_persistent_store(
            'wyoming:connection_policy',
            default=WyomingConnectionPolicy.LOCAL_ONLY,
            mapper=_load_connection_policy,
        ),
    )
    allowed_peers: tuple[str, ...] = field(
        default_factory=lambda: read_from_persistent_store(
            'wyoming:allowed_peers',
            default=(),
            mapper=_load_allowed_peers,
        ),
    )
    is_zeroconf_enabled: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'wyoming:is_zeroconf_enabled',
            default=True,
        ),
    )
    satellite_status: WyomingSatelliteStatus = WyomingSatelliteStatus.STOPPED
    satellite_client: str = ''
    engines_status: WyomingEnginesStatus = WyomingEnginesStatus.STOPPED
    active_engine_requests: int = 0


class WyomingAction(BaseAction):
    """Base class for Wyoming actions."""


class WyomingSetSatelliteEnabledAction(WyomingAction):
    """Enable or disable the Wyoming satellite listener."""

    enabled: bool


class WyomingSetEnginesEnabledAction(WyomingAction):
    """Enable or disable the Wyoming ASR/TTS/handle listener."""

    enabled: bool


class WyomingSetConnectionPolicyAction(WyomingAction):
    """Set the listener's narrowly scoped connection policy."""

    policy: WyomingConnectionPolicy


class WyomingSetAllowedPeersAction(WyomingAction):
    """Replace the explicit remote Home Assistant IP/CIDR allowlist."""

    peers: list[str]


class WyomingSetZeroconfEnabledAction(WyomingAction):
    """Enable or disable mDNS advertisements while remotely reachable."""

    enabled: bool


class WyomingReportSatelliteStatusAction(WyomingAction):
    """Report the active satellite listener state."""

    status: WyomingSatelliteStatus
    client: str = ''


class WyomingReportEnginesStatusAction(WyomingAction):
    """Report engine-listener activity."""

    status: WyomingEnginesStatus = WyomingEnginesStatus.STOPPED
    active_requests: int = 0


class WyomingSatelliteWakeAction(WyomingAction):
    """Hand an utterance to Home Assistant after a local wake-word detection.

    Dispatched by the speech-recognition reducer when a ``WakeMode.HOME_ASSISTANT``
    trigger fires. The satellite detects the wake word on-device and asks Home
    Assistant to run its pipeline from the ASR stage, so Home Assistant needs no
    wake-word engine of its own and the microphone is only streamed for the
    duration of the utterance.
    """

    phrase: str = ''
    detector: str = ''


class WyomingEvent(BaseEvent):
    """Base class for Wyoming events."""


class WyomingSatelliteWakeEvent(WyomingEvent):
    """Ask the satellite connection to start a Home Assistant pipeline run."""

    phrase: str = ''
    detector: str = ''
