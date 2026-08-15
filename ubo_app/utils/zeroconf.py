"""Shared Zeroconf/mDNS registration — one `AsyncZeroconf` instance per process.

Every service that wants mDNS discoverability shares this one instance
instead of each opening its own multicast socket. Wyoming manages its own
separate registry (`ubo_app/services/090-wyoming/setup.py`'s
`_ZeroconfRegistry`) since its registrations are gated by a user-facing
zeroconf toggle that doesn't apply here — this module is for everything
else, starting with the gRPC control API's `_uborpc._tcp` advertisement.
"""

from __future__ import annotations

import socket

from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from ubo_app.logger import logger


class _SharedZeroconf:
    def __init__(self) -> None:
        self._zeroconf: AsyncZeroconf | None = None
        self._services: dict[str, AsyncServiceInfo] = {}

    async def register(
        self,
        *,
        service_type: str,
        name: str,
        address: str,
        port: int,
    ) -> None:
        """Advertise one service under *name*, replacing any prior registration."""
        await self.unregister(name)
        zeroconf = self._zeroconf
        if zeroconf is None:
            zeroconf = AsyncZeroconf()
            self._zeroconf = zeroconf
        info = AsyncServiceInfo(
            service_type,
            name,
            addresses=[socket.inet_aton(address)],
            port=port,
        )
        try:
            await zeroconf.async_register_service(info)
            self._services[name] = info
        except Exception:
            logger.exception(
                'Failed to register zeroconf service',
                extra={'service_name': name},
            )

    async def unregister(self, name: str) -> None:
        """Remove one advertised service, if registered.

        Closes the shared instance once nothing is left registered, so an
        idle process holds no multicast socket open.
        """
        info = self._services.pop(name, None)
        if info is None or self._zeroconf is None:
            return
        try:
            await self._zeroconf.async_unregister_service(info)
        except Exception:  # noqa: BLE001
            logger.warning(
                'Failed to unregister zeroconf service',
                extra={'service_name': name},
            )
        if not self._services:
            await self._zeroconf.async_close()
            self._zeroconf = None


_shared = _SharedZeroconf()


async def register_service(
    *,
    service_type: str,
    name: str,
    address: str,
    port: int,
) -> None:
    """Advertise *name* on the shared zeroconf instance."""
    await _shared.register(
        service_type=service_type,
        name=name,
        address=address,
        port=port,
    )


async def unregister_service(name: str) -> None:
    """Remove *name* from the shared zeroconf instance."""
    await _shared.unregister(name)
