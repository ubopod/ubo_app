"""Tests for Wyoming listener peer authorization."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

from ubo_app.store.services.wyoming import WyomingConnectionPolicy

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

security = import_module('security')
is_peer_allowed = security.is_peer_allowed
listener_host = security.listener_host
remote_listener_is_configured = security.remote_listener_is_configured


def test_local_only_never_accepts_lan_peers() -> None:
    """The safe default cannot send microphone audio to the LAN."""
    assert is_peer_allowed('127.0.0.1', WyomingConnectionPolicy.LOCAL_ONLY, ())
    assert not is_peer_allowed('192.168.1.20', WyomingConnectionPolicy.LOCAL_ONLY, ())
    assert listener_host(WyomingConnectionPolicy.LOCAL_ONLY) == '127.0.0.1'


def test_policy_is_honored_when_it_is_not_the_canonical_enum_member() -> None:
    """A policy that only compares equal must still narrow the bind and access.

    ``WyomingConnectionPolicy`` is a ``StrEnum`` that reaches this code through
    the store and the gRPC surface, so the value is not guaranteed to be the
    canonical member. Identity checks would silently bind ``local-only`` to all
    interfaces and leave both remote policies with no authorized network.
    """
    assert listener_host('local-only') == '127.0.0.1'
    assert is_peer_allowed(
        '172.20.0.4',
        'docker-home-assistant',
        (),
        ('172.20.0.0/16',),
    )
    assert is_peer_allowed('192.168.1.20', 'allowlist', ('192.168.1.20',))
    assert remote_listener_is_configured('allowlist', ('192.168.1.20',))


def test_docker_policy_only_accepts_the_resolved_bridge_subnet() -> None:
    """Container-only access does not accidentally become general LAN access."""
    bridge = ('172.20.0.0/16',)

    assert is_peer_allowed(
        '172.20.0.4',
        WyomingConnectionPolicy.DOCKER_HOME_ASSISTANT,
        (),
        bridge,
    )
    assert not is_peer_allowed(
        '192.168.1.20',
        WyomingConnectionPolicy.DOCKER_HOME_ASSISTANT,
        (),
        bridge,
    )
    assert (
        listener_host(WyomingConnectionPolicy.DOCKER_HOME_ASSISTANT) == '0.0.0.0'  # noqa: S104
    )


def test_docker_policy_does_not_trust_the_whole_private_range() -> None:
    """A LAN numbered inside Docker's private space is not a Docker bridge.

    The listener binds all interfaces under this policy, so trusting the range
    Docker draws from rather than the subnet it actually assigned would
    authorize every host on such a LAN to stream the microphone.
    """
    bridge = ('172.20.0.0/16',)

    assert not is_peer_allowed(
        '172.31.4.9',
        WyomingConnectionPolicy.DOCKER_HOME_ASSISTANT,
        (),
        bridge,
    )


def test_docker_policy_is_fail_closed_without_a_resolved_bridge() -> None:
    """An unresolvable bridge admits nobody rather than everybody."""
    assert not is_peer_allowed(
        '172.20.0.4',
        WyomingConnectionPolicy.DOCKER_HOME_ASSISTANT,
        (),
        (),
    )
    assert not remote_listener_is_configured(
        WyomingConnectionPolicy.DOCKER_HOME_ASSISTANT,
        (),
        (),
    )


def test_allowlist_accepts_only_explicit_ip_or_network() -> None:
    """Remote Home Assistant use requires an explicit persisted allowlist."""
    peers = ('192.168.1.20', '10.0.0.0/24')

    assert is_peer_allowed('192.168.1.20', WyomingConnectionPolicy.ALLOWLIST, peers)
    assert is_peer_allowed('10.0.0.8', WyomingConnectionPolicy.ALLOWLIST, peers)
    assert not is_peer_allowed('192.168.1.21', WyomingConnectionPolicy.ALLOWLIST, peers)
    assert not is_peer_allowed('not-an-ip', WyomingConnectionPolicy.ALLOWLIST, peers)


def test_empty_allowlist_does_not_start_a_remote_listener() -> None:
    """A selected allowlist policy remains fail-closed until peers are entered."""
    assert not remote_listener_is_configured(
        WyomingConnectionPolicy.ALLOWLIST,
        (),
    )
    assert remote_listener_is_configured(
        WyomingConnectionPolicy.ALLOWLIST,
        ('192.168.1.20',),
    )
    assert remote_listener_is_configured(
        WyomingConnectionPolicy.DOCKER_HOME_ASSISTANT,
        (),
        ('172.20.0.0/16',),
    )
