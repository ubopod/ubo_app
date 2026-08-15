"""Network-boundary checks for the unauthenticated Wyoming protocol."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

from immutable import Immutable

from ubo_app.store.services.wyoming import (
    WyomingAccessPolicy,
    WyomingAccessPolicyKind,
)


def authorized_networks(
    policies: tuple[WyomingAccessPolicy, ...],
    docker_networks: tuple[str, ...],
) -> tuple[str, ...]:
    """Return every network the configured policies admit, besides loopback.

    Policies are a union: each one contributes its networks and a peer needs to
    match only one of them, which is what lets a Docker bridge and explicit LAN
    addresses be permitted at the same time.
    """
    networks: list[str] = []
    for policy in policies:
        if policy.kind == WyomingAccessPolicyKind.DOCKER:
            networks.extend(docker_networks)
        elif policy.kind == WyomingAccessPolicyKind.NETWORK and policy.value:
            networks.append(policy.value)
    return tuple(networks)


def remote_listener_is_configured(
    policies: tuple[WyomingAccessPolicy, ...],
    docker_networks: tuple[str, ...] = (),
) -> bool:
    """Return whether a non-local listener has a permitted source set.

    A Docker policy whose bridge could not be resolved contributes no networks,
    so a device configured only that way must not open a listener on all
    interfaces until the daemon can be read.
    """
    return bool(authorized_networks(policies, docker_networks))


def listener_host(policies: tuple[WyomingAccessPolicy, ...]) -> str:
    """Return the narrowest bind address these policies permit.

    No policies means nothing off-device was ever permitted, so the listener
    stays on loopback rather than being reachable and merely rejecting peers.
    """
    return '0.0.0.0' if policies else '127.0.0.1'  # noqa: S104


def is_peer_allowed(
    peer: str,
    policies: tuple[WyomingAccessPolicy, ...],
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
        for network in authorized_networks(policies, docker_networks)
    )


class PeerAccess(Immutable):
    """The resolved answer to who may open a Wyoming connection."""

    policies: tuple[WyomingAccessPolicy, ...] = ()
    docker_networks: tuple[str, ...] = ()

    @property
    def host(self) -> str:
        """Return the narrowest bind address this access permits."""
        return listener_host(self.policies)

    @property
    def is_configured(self) -> bool:
        """Return whether a listener beyond loopback has a permitted source."""
        return not self.policies or remote_listener_is_configured(
            self.policies,
            self.docker_networks,
        )

    @property
    def wants_docker_networks(self) -> bool:
        """Whether resolving the Docker bridge is needed to apply these policies."""
        return any(
            policy.kind == WyomingAccessPolicyKind.DOCKER for policy in self.policies
        )

    def allows(self, peer: str) -> bool:
        """Authorize a peer before it reaches the microphone or the engines."""
        return is_peer_allowed(peer, self.policies, self.docker_networks)
