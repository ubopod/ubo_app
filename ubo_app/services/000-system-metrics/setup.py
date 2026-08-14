# ruff: noqa: D100
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

from ubo_app.logger import logger
from ubo_app.store.core.view_registry import (
    register_home_view_data_provider,
    register_home_view_dependency,
)
from ubo_app.store.main import store
from ubo_app.store.services.system import (
    SystemMetricsUpdateAction,
    SystemStorageUpdateAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.units import convert_temperature_c, resolve_unit_system

if TYPE_CHECKING:
    from ubo_app.store.services.localization import UnitSystem
    from ubo_app.utils.types import Subscriptions

# Only dispatch CPU/RAM if delta exceeds this threshold (percentage points)
_METRICS_THRESHOLD = 0.5
# Same idea for the CPU die temperature, in degrees Celsius.
_TEMPERATURE_THRESHOLD = 0.5
# Network counters move constantly, so an unconditioned comparison would defeat
# the debounce entirely and turn a mostly-idle loop into a guaranteed 1 Hz
# dispatch. A rate has to clear *both* floors to count as a change.
_NETWORK_ABSOLUTE_THRESHOLD = 4 * 1024  # bytes/second
_NETWORK_RELATIVE_THRESHOLD = 0.1  # fraction of the previous rate

# Disk usage moves over minutes, not seconds; polling it at 1 Hz is wasted work.
_STORAGE_INTERVAL = 30

# Where the Raspberry Pi exposes CPU temperature when psutil finds no sensor.
_THERMAL_ZONE = Path('/sys/class/thermal/thermal_zone0/temp')

# Cached last-dispatched values to skip redundant dispatches.
# Container pattern avoids ``global`` statements.
_last: dict[str, float | str | None] = {
    'cpu': -1.0,
    'ram': -1.0,
    'temperature': None,
    'upload': -1.0,
    'download': -1.0,
    'unit_system': None,
}

# Previous cumulative network counters, for turning them into a rate.
_network_sample: dict[str, float] = {'time': 0.0, 'sent': 0.0, 'received': 0.0}


def read_cpu_temperature() -> float | None:
    """Return the CPU temperature in Celsius, or ``None`` if unavailable."""
    # `sensors_temperatures` only exists on Linux, so it is absent from the
    # stubs when type-checking on macOS — hence the guarded lookup.
    read = getattr(psutil, 'sensors_temperatures', None)
    try:
        sensors = read() if read else {}
    except OSError:
        sensors = {}

    for readings in sensors.values():
        for reading in readings:
            if reading.current:
                return float(reading.current)

    try:
        return int(_THERMAL_ZONE.read_text()) / 1000
    except (OSError, ValueError):
        return None


def read_network_rates() -> tuple[float, float]:
    """Return (upload, download) in bytes/second since the previous call."""
    counters = psutil.net_io_counters()
    now = time.monotonic()
    elapsed = now - _network_sample['time']

    previous_sent = _network_sample['sent']
    previous_received = _network_sample['received']
    _network_sample.update(
        time=now,
        sent=counters.bytes_sent,
        received=counters.bytes_recv,
    )

    # First sample has no baseline, and a counter reset (interface reload)
    # would otherwise show up as an enormous spike.
    if elapsed <= 0 or previous_sent == 0:
        return 0.0, 0.0

    upload = max(0.0, counters.bytes_sent - previous_sent) / elapsed
    download = max(0.0, counters.bytes_recv - previous_received) / elapsed
    return upload, download


def _has_network_change(key: str, rate: float) -> bool:
    previous = float(_last[key] or 0)
    delta = abs(rate - previous)
    return (
        delta > _NETWORK_ABSOLUTE_THRESHOLD
        and delta > previous * _NETWORK_RELATIVE_THRESHOLD
    )


def _has_temperature_change(temperature: float | None) -> bool:
    previous = _last['temperature']
    if temperature is None or previous is None:
        return temperature is not previous
    return abs(temperature - float(previous)) > _TEMPERATURE_THRESHOLD


@store.with_state(
    lambda state: resolve_unit_system(
        state.localization.unit_system,
        state.localization.location.country_code
        if state.localization.location
        else None,
    ),
)
def _effective_unit_system(unit_system: UnitSystem) -> UnitSystem:
    return unit_system


def read_metrics() -> None:
    """Read system metrics and dispatch update action.

    Skips dispatch when values haven't changed meaningfully to reduce
    autorun evaluations and state churn.
    """
    cpu_percent = psutil.cpu_percent(interval=None)
    ram_percent = psutil.virtual_memory().percent
    temperature = read_cpu_temperature()
    upload, download = read_network_rates()
    load_average_1, load_average_5, load_average_15 = os.getloadavg()
    unit_system = _effective_unit_system()

    cpu_changed = abs(cpu_percent - float(_last['cpu'] or 0)) > _METRICS_THRESHOLD
    ram_changed = abs(ram_percent - float(_last['ram'] or 0)) > _METRICS_THRESHOLD
    # A unit-system flip forces one dispatch even if the reading itself held
    # steady — otherwise a settings change would sit stale until the CPU
    # temperature next moved by more than the debounce threshold.
    unit_system_changed = unit_system != _last['unit_system']

    if not (
        cpu_changed
        or ram_changed
        or _has_temperature_change(temperature)
        or unit_system_changed
        or _has_network_change('upload', upload)
        or _has_network_change('download', download)
    ):
        return

    if temperature is None:
        temperature_display_value, temperature_display_unit = None, None
    else:
        temperature_display_value, temperature_display_unit = convert_temperature_c(
            temperature,
            unit_system,
        )

    _last['cpu'] = cpu_percent
    _last['ram'] = ram_percent
    _last['temperature'] = temperature
    _last['upload'] = upload
    _last['download'] = download
    _last['unit_system'] = unit_system

    logger.verbose(
        '[SystemMetrics] Dispatching: cpu=%.1f, ram=%.1f',
        cpu_percent,
        ram_percent,
    )

    store.dispatch(
        SystemMetricsUpdateAction(
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
            cpu_temperature_celsius=temperature,
            cpu_temperature_display_value=temperature_display_value,
            cpu_temperature_display_unit=temperature_display_unit,
            load_average_1=load_average_1,
            load_average_5=load_average_5,
            load_average_15=load_average_15,
            boot_time=psutil.boot_time(),
            network_upload_bps=upload,
            network_download_bps=download,
        ),
    )


def read_storage() -> None:
    """Read disk usage of the root filesystem and dispatch it."""
    usage = psutil.disk_usage('/')
    store.dispatch(
        SystemStorageUpdateAction(
            disk_total_bytes=usage.total,
            disk_used_bytes=usage.used,
            disk_percent=usage.percent,
        ),
    )


async def _monitor_metrics(end_event: asyncio.Event) -> None:
    """Periodically read system metrics."""
    while not end_event.is_set():
        read_metrics()
        await asyncio.sleep(1)


async def _monitor_storage(end_event: asyncio.Event) -> None:
    """Periodically read disk usage."""
    while not end_event.is_set():
        read_storage()
        await asyncio.sleep(_STORAGE_INTERVAL)


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
    # Register home view data providers for decoupled view computation
    unregister_cpu_data = register_home_view_data_provider(
        'system:cpu',
        lambda s: ('cpu_percent', s.system.cpu_percent),
    )
    unregister_ram_data = register_home_view_data_provider(
        'system:ram',
        lambda s: ('ram_percent', s.system.ram_percent),
    )

    read_metrics()

    end_event = asyncio.Event()
    create_task(_monitor_metrics(end_event))
    create_task(_monitor_storage(end_event))

    logger.info('[SystemMetrics] Service started')
    return [
        end_event.set,
        unregister_cpu,
        unregister_ram,
        unregister_cpu_data,
        unregister_ram_data,
    ]
