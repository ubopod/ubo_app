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


class WyomingAccessPolicyKind(StrEnum):
    """A source of permitted Wyoming peers."""

    DOCKER = 'docker'
    NETWORK = 'network'


class WyomingAccessPolicy(Immutable):
    """One permitted source of Wyoming connections.

    Policies combine: a peer is admitted if it falls inside *any* of them, so a
    Docker bridge and explicit LAN addresses can be permitted at once. ``value``
    is the IP or CIDR for ``NETWORK`` and empty for ``DOCKER``, whose subnets are
    resolved from the daemon at reconcile time rather than being configured.

    No policies at all is the safe default: the listener binds loopback and
    nothing off-device can reach it.
    """

    kind: WyomingAccessPolicyKind
    value: str = ''


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


def normalize_network(value: object) -> str | None:
    """Return the canonical IP/CIDR form of *value*, or None if it is not one.

    Hostnames are rejected on purpose: they resolve at an unpredictable moment to
    an address nobody reviewed, which is not a boundary worth trusting for an
    unauthenticated protocol.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    try:
        return (
            str(ip_network(stripped, strict=False))
            if '/' in stripped
            else str(ip_address(stripped))
        )
    except ValueError:
        return None


def normalize_access_policies(
    policies: Iterable[object],
) -> tuple[WyomingAccessPolicy, ...]:
    """Return de-duplicated, canonical policies, dropping anything malformed.

    Order is stable and independent of insertion order so the menu does not
    reshuffle under the user, and Docker sorts first because it is the one whose
    subnets the device resolves for itself.
    """
    docker: list[WyomingAccessPolicy] = []
    networks: set[str] = set()
    for policy in policies:
        kind = getattr(policy, 'kind', None)
        if kind == WyomingAccessPolicyKind.DOCKER:
            docker = [WyomingAccessPolicy(kind=WyomingAccessPolicyKind.DOCKER)]
        elif kind == WyomingAccessPolicyKind.NETWORK:
            normalized = normalize_network(getattr(policy, 'value', None))
            if normalized is not None:
                networks.add(normalized)
    return (
        *docker,
        *(
            WyomingAccessPolicy(kind=WyomingAccessPolicyKind.NETWORK, value=value)
            for value in sorted(networks)
        ),
    )


def _load_access_policies(value: object) -> tuple[WyomingAccessPolicy, ...]:
    """Rebuild the policy list from persistence, migrating the older layout.

    The first layout stored a single ``connection_policy`` enum plus a separate
    peer list, which could not express "Docker *and* these addresses". Migration
    maps it onto the equivalent set; ``local-only`` becomes no policies at all,
    which is the same loopback-only listener it always described.
    """
    if isinstance(value, list | tuple):
        return normalize_access_policies(
            WyomingAccessPolicy(
                kind=WyomingAccessPolicyKind(entry['kind']),
                value=entry.get('value', ''),
            )
            for entry in value
            if isinstance(entry, dict) and entry.get('kind') in _POLICY_KIND_VALUES
        )
    return _migrated_access_policies()


_POLICY_KIND_VALUES = {kind.value for kind in WyomingAccessPolicyKind}


def _migrated_access_policies() -> tuple[WyomingAccessPolicy, ...]:
    """Build policies from the pre-combination keys, or none for a fresh install."""
    legacy_policy = read_from_persistent_store(
        'wyoming:connection_policy',
        default='local-only',
    )
    if legacy_policy == 'docker-home-assistant':
        return (WyomingAccessPolicy(kind=WyomingAccessPolicyKind.DOCKER),)
    if legacy_policy == 'allowlist':
        peers = read_from_persistent_store('wyoming:allowed_peers', default=[])
        return normalize_access_policies(
            WyomingAccessPolicy(
                kind=WyomingAccessPolicyKind.NETWORK,
                value=peer,
            )
            for peer in (peers if isinstance(peers, list | tuple) else ())
            if isinstance(peer, str)
        )
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
    access_policies: tuple[WyomingAccessPolicy, ...] = field(
        # The mapper is applied here rather than passed to the reader: the reader
        # returns ``default`` untouched when the key is absent, which would skip
        # the migration on exactly the installs that need it.
        default_factory=lambda: _load_access_policies(
            read_from_persistent_store('wyoming:access_policies', default=None),
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


class WyomingAddAccessPolicyAction(WyomingAction):
    """Permit one more source of Wyoming connections."""

    kind: WyomingAccessPolicyKind
    value: str = ''


class WyomingRemoveAccessPolicyAction(WyomingAction):
    """Withdraw one permitted source of Wyoming connections."""

    kind: WyomingAccessPolicyKind
    value: str = ''


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
