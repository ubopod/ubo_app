# ruff: noqa: D100
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psutil

from ubo_app.store.main import store
from ubo_app.store.services.system import SystemMetricsUpdateAction
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


def read_metrics() -> None:
    """Read system metrics and dispatch update action."""
    cpu_percent = psutil.cpu_percent(interval=None)
    ram_percent = psutil.virtual_memory().percent
    clock = datetime.now(tz=UTC).strftime('%H:%M')

    store.dispatch(
        SystemMetricsUpdateAction(
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
            clock=clock,
        ),
    )


async def _monitor_metrics(end_event: asyncio.Event) -> None:
    """Periodically read system metrics."""
    while not end_event.is_set():
        read_metrics()
        await asyncio.sleep(1)


def init_service() -> Subscriptions:
    """Initialize the system-metrics service."""
    read_metrics()

    end_event = asyncio.Event()
    create_task(_monitor_metrics(end_event))

    return [end_event.set]
