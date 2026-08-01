"""Network-boundary checks for the unauthenticated Wyoming protocol."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

from immutable import Immutable

from ubo_app.store.services.wyoming import WyomingConnectionPolicy


def _authorized_networks(
    policy: WyomingConnectionPolicy,
    allowed_peers: tuple[str, ...],
    docker_networks: tuple[str, ...],
) -> tuple[str, ...]:
    """Return the only networks a policy may admit besides loopback."""
    if policy == WyomingConnectionPolicy.DOCKER_HOME_ASSISTANT:
        return docker_networks
    if policy == WyomingConnectionPolicy.ALLOWLIST:
        return allowed_peers
    return ()


def remote_listener_is_configured(
    policy: WyomingConnectionPolicy,
    allowed_peers: tuple[str, ...],
    docker_networks: tuple[str, ...] = (),
) -> bool:
    """Return whether a non-local listener has a permitted source set.

    A Docker policy whose bridge could not be resolved has no permitted source,
    so it must not open a listener on all interfaces.
    """
    return bool(_authorized_networks(policy, allowed_peers, docker_networks))


def listener_host(policy: WyomingConnectionPolicy) -> str:
    """Return the narrowest bind address compatible with a policy."""
    return '127.0.0.1' if policy == WyomingConnectionPolicy.LOCAL_ONLY else '0.0.0.0'  # noqa: S104


def is_peer_allowed(
    peer: str,
    policy: WyomingConnectionPolicy,
    allowed_peers: tuple[str, ...],
    docker_networks: tuple[str, ...] = (),
) -> bool:
    """Authorize an IP peer before it can request microphone audio or engines.

    ``docker_networks`` are the subnets Docker actually assigned to the shared
    bridge, resolved at reconcile time. They are never assumed: the private
    ranges Docker draws from are ordinary RFC1918 space, so trusting the range
    rather than the live subnet would authorize every host on a LAN that
    happens to be numbered inside it.
    """
    try:
        address: IPv4Address | IPv6Address = ip_address(peer)
    except ValueError:
        return False

    if address.is_loopback:
        return True

    return any(
        address in ip_network(network, strict=False)
        for network in _authorized_networks(policy, allowed_peers, docker_networks)
    )


class PeerAccess(Immutable):
    """The resolved answer to who may open a Wyoming connection."""

    policy: WyomingConnectionPolicy
    allowed_peers: tuple[str, ...] = ()
    docker_networks: tuple[str, ...] = ()

    @property
    def host(self) -> str:
        """Return the narrowest bind address this access permits."""
        return listener_host(self.policy)

    @property
    def is_configured(self) -> bool:
        """Return whether a listener beyond loopback has a permitted source."""
        return self.policy == WyomingConnectionPolicy.LOCAL_ONLY or (
            remote_listener_is_configured(
                self.policy,
                self.allowed_peers,
                self.docker_networks,
            )
        )

    def allows(self, peer: str) -> bool:
        """Authorize a peer before it reaches the microphone or the engines."""
        return is_peer_allowed(
            peer,
            self.policy,
            self.allowed_peers,
            self.docker_networks,
        )
