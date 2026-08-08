# ruff: noqa: D100
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class SystemAction(BaseAction):
    """Base action for system metrics."""


class SystemMetricsUpdateAction(SystemAction):
    """Update the fast-moving system metrics.

    Dispatched by the system-metrics service's one-second loop, debounced so
    that only meaningful changes reach the store.
    """

    cpu_percent: float
    ram_percent: float
    cpu_temperature_celsius: float | None = None
    load_average_1: float = 0.0
    load_average_5: float = 0.0
    load_average_15: float = 0.0
    boot_time: float = 0.0
    network_upload_bps: float = 0.0
    network_download_bps: float = 0.0


class SystemStorageUpdateAction(SystemAction):
    """Update disk usage.

    Dispatched by a slower loop than the metrics above — disk usage moves over
    minutes, not seconds.
    """

    disk_total_bytes: int
    disk_used_bytes: int
    disk_percent: float


class SystemEvent(BaseEvent):
    """Base event for system metrics."""


class SystemState(Immutable):
    """State for system metrics used in UI rendering.

    The fields are deliberately flat scalars: the slice is streamed to remote
    clients as a whole, and nested types would each become a wrapper message on
    the wire for no benefit.
    """

    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    # The clock lives in `LocalizationState`: it is the time at the device's
    # *location*, which this service has no way to know.
    # `None` where the platform exposes no CPU thermal sensor (desktop dev).
    cpu_temperature_celsius: float | None = None
    load_average_1: float = 0.0
    load_average_5: float = 0.0
    load_average_15: float = 0.0
    # Boot time rather than uptime: uptime would change every second and churn
    # the store for every connected client, while boot time is a constant the
    # client can subtract from its own clock.
    boot_time: float = 0.0
    disk_total_bytes: int = 0
    disk_used_bytes: int = 0
    disk_percent: float = 0.0
    network_upload_bps: float = 0.0
    network_download_bps: float = 0.0
