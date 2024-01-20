# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import Sequence

from redux import BaseAction, BaseEvent, Immutable


class IpAction(BaseAction):
    ...


class IpEvent(BaseEvent):
    ...


class IpUpdateRequestAction(IpAction):
    reset: bool = False


class IpUpdateAction(IpAction):
    interfaces: Sequence[IpNetworkInterface]


class IpUpdateRequestEvent(IpEvent):
    ...


class IpNetworkInterface(Immutable):
    name: str
    ip_addresses: Sequence[str]


class IpState(Immutable):
    interfaces: Sequence[IpNetworkInterface]
