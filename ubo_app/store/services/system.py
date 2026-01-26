# ruff: noqa: D100
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class SystemAction(BaseAction):
    """Base action for system metrics."""


class SystemMetricsUpdateAction(SystemAction):
    """Update system metrics (CPU, RAM, clock).

    Dispatched periodically by the system-metrics service.
    """

    cpu_percent: float
    ram_percent: float
    clock: str  # Format: "HH:MM"


class SystemEvent(BaseEvent):
    """Base event for system metrics."""


class SystemState(Immutable):
    """State for system metrics used in UI rendering.

    These values are updated periodically and used to compute
    HomeViewData and StatusBarData.
    """

    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    clock: str = ''
