"""Resolution of the Docker bridge a locally hosted Home Assistant connects from."""

from __future__ import annotations

import asyncio
import contextlib
from ipaddress import ip_network

from constants import UBO_NET_NAME

from ubo_app.logger import logger


def _read_bridge_subnets() -> tuple[str, ...]:
    """Read the subnets Docker assigned to the shared bridge, blocking."""
    import docker

    client = None
    try:
        client = docker.from_env()
        network = client.networks.get(UBO_NET_NAME)
        configs = network.attrs.get('IPAM', {}).get('Config') or []
        subnets: list[str] = []
        for config in configs:
            subnet = config.get('Subnet') if isinstance(config, dict) else None
            if not isinstance(subnet, str):
                continue
            try:
                subnets.append(str(ip_network(subnet, strict=False)))
            except ValueError:
                logger.warning('Ignoring malformed Docker subnet %s', subnet)
        return tuple(sorted(subnets))
    except Exception:
        logger.exception('Unable to resolve the Docker bridge for Wyoming')
        return ()
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()


async def resolve_bridge_subnets() -> tuple[str, ...]:
    """Resolve the bridge off the event loop; empty means "do not open up"."""
    return await asyncio.to_thread(_read_bridge_subnets)
