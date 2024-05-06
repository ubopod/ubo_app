# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Sequence


class IpAction(BaseAction): ...


class IpEvent(BaseEvent): ...


class IpUpdateInterfacesAction(IpAction):
    interfaces: Sequence[IpNetworkInterface]


class IpSetIsConnectedAction(IpAction):
    is_connected: bool


class IpNetworkInterface(Immutable):
    name: str
    ip_addresses: Sequence[str]


class IpState(Immutable):
    interfaces: Sequence[IpNetworkInterface]
    is_connected: bool | None = None
