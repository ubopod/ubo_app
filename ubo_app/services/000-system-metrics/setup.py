# ruff: noqa: D100
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psutil

from ubo_app.logger import logger
from ubo_app.store.core.view_registry import (
    register_home_view_dependency,
    register_status_bar_dependency,
)
from ubo_app.store.main import store
from ubo_app.store.services.system import SystemMetricsUpdateAction
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


def read_metrics() -> None:
    """Read system metrics and dispatch update action."""
    cpu_percent = psutil.cpu_percent(interval=None)
    ram_percent = psutil.virtual_memory().percent
    # Use local timezone for clock display
    local_tz = datetime.now(tz=UTC).astimezone().tzinfo
    clock = datetime.now(tz=local_tz).strftime('%H:%M')

    logger.info(
        '[SystemMetrics] Dispatching: cpu=%.1f, ram=%.1f, clock=%s',
        cpu_percent,
        ram_percent,
        clock,
    )

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
    logger.info('[SystemMetrics] Service initializing...')

    # Register view dependencies for home view and status bar
    unregister_cpu = register_home_view_dependency(
        'system:cpu',
        lambda s: s.system.cpu_percent,
    )
    unregister_ram = register_home_view_dependency(
        'system:ram',
        lambda s: s.system.ram_percent,
    )
    unregister_clock = register_status_bar_dependency(
        'system:clock',
        lambda s: s.system.clock,
    )

    read_metrics()

    end_event = asyncio.Event()
    create_task(_monitor_metrics(end_event))

    logger.info('[SystemMetrics] Service started')
    return [end_event.set, unregister_cpu, unregister_ram, unregister_clock]
