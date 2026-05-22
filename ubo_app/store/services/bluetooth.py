# ruff: noqa: D100, D101
from __future__ import annotations

from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Sequence


class BluetoothDevice(Immutable):
    address: str
    name: str
    icon: str | None = None
    paired: bool = False
    connected: bool = False
    trusted: bool = False
    rssi: int | None = None


class BluetoothAction(BaseAction): ...


class BluetoothUpdateAction(BluetoothAction):
    devices: Sequence[BluetoothDevice]
    is_powered: bool
    is_scanning: bool


class BluetoothUpdateRequestAction(BluetoothAction):
    reset: bool = False


class BluetoothEvent(BaseEvent): ...


class BluetoothUpdateRequestEvent(BluetoothEvent): ...


class BluetoothState(Immutable):
    is_powered: bool
    is_scanning: bool
    devices: Sequence[BluetoothDevice] | None
