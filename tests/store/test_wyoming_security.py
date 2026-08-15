"""Who may open a connection to the unauthenticated Wyoming listeners.

Policies combine: a peer is admitted if it matches any of them, so a Docker
bridge and explicit LAN addresses can be permitted at the same time. Permitting
nothing is the safe default — the listener stays on loopback rather than being
reachable and merely rejecting peers.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

from ubo_app.store.services.wyoming import (
    WyomingAccessPolicy,
    WyomingAccessPolicyKind,
)

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

security = import_module('security')
is_peer_allowed = security.is_peer_allowed
listener_host = security.listener_host
PeerAccess = security.PeerAccess

DOCKER = WyomingAccessPolicy(kind=WyomingAccessPolicyKind.DOCKER)


def _network(value: str) -> WyomingAccessPolicy:
    return WyomingAccessPolicy(kind=WyomingAccessPolicyKind.NETWORK, value=value)


def test_permitting_nothing_keeps_the_listener_on_loopback() -> None:
    """With no policy the device must not be reachable off-box at all."""
    assert listener_host(()) == '127.0.0.1'
    assert is_peer_allowed('127.0.0.1', ())
    assert not is_peer_allowed('192.168.1.20', ())
    # Loopback-only still counts as configured: it is a deliberate posture.
    assert PeerAccess().is_configured


def test_a_docker_policy_admits_only_the_resolved_bridge() -> None:
    """Docker subnets are ordinary RFC1918 space, so only the live one counts."""
    access = PeerAccess(policies=(DOCKER,), docker_networks=('172.18.0.0/16',))

    assert access.allows('172.18.0.5')
    assert not access.allows('192.168.1.20')
    assert access.host == '0.0.0.0'  # noqa: S104


def test_an_unresolvable_docker_bridge_opens_nothing() -> None:
    """A Docker policy with no resolved subnet must not open all interfaces."""
    access = PeerAccess(policies=(DOCKER,), docker_networks=())

    assert not access.is_configured
    assert not access.allows('172.18.0.5')


def test_a_network_policy_admits_its_address_or_range() -> None:
    """An explicit address or CIDR admits exactly what it names."""
    access = PeerAccess(policies=(_network('192.168.1.20'), _network('10.0.0.0/24')))

    assert access.allows('192.168.1.20')
    assert access.allows('10.0.0.8')
    assert not access.allows('192.168.1.21')
    assert not access.allows('not-an-ip')


def test_policies_combine_rather_than_replace() -> None:
    """The whole point of the model: Docker *and* an address, at once.

    Each policy contributes its networks and a peer needs to match only one, so
    adding the Docker bridge must not withdraw an address permitted before it.
    """
    access = PeerAccess(
        policies=(DOCKER, _network('192.168.1.20')),
        docker_networks=('172.18.0.0/16',),
    )

    assert access.allows('172.18.0.5'), 'docker bridge lost'
    assert access.allows('192.168.1.20'), 'explicit address lost'
    assert not access.allows('192.168.1.21')


def test_a_broken_docker_bridge_does_not_revoke_the_other_policies() -> None:
    """An unresolvable bridge must not take the working policies down with it."""
    access = PeerAccess(policies=(DOCKER, _network('192.168.1.20')))

    assert access.is_configured
    assert access.allows('192.168.1.20')
    assert not access.allows('172.18.0.5')


def test_loopback_is_always_admitted() -> None:
    """On-device clients are permitted whatever the policies say."""
    for policies in ((), (DOCKER,), (_network('192.168.1.20'),)):
        assert is_peer_allowed('127.0.0.1', policies)


def test_docker_resolution_is_only_requested_when_needed() -> None:
    """Status changes must not put the Docker daemon in the hot path."""
    assert not PeerAccess(policies=(_network('192.168.1.20'),)).wants_docker_networks
    assert not PeerAccess().wants_docker_networks
    assert PeerAccess(policies=(DOCKER,)).wants_docker_networks
