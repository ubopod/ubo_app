# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import BaseEvent, InitAction, InitializationActionError, ReducerResult

from ubo_app.store.services.system import (
    SystemAction,
    SystemMetricsUpdateAction,
    SystemState,
    SystemStorageUpdateAction,
)

Action = InitAction | SystemAction


def reducer(
    state: SystemState | None,
    action: Action,
) -> ReducerResult[SystemState, Action, BaseEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return SystemState()
        raise InitializationActionError(action)

    match action:
        case SystemMetricsUpdateAction():
            return replace(
                state,
                cpu_percent=action.cpu_percent,
                ram_percent=action.ram_percent,
                cpu_temperature_celsius=action.cpu_temperature_celsius,
                load_average_1=action.load_average_1,
                load_average_5=action.load_average_5,
                load_average_15=action.load_average_15,
                boot_time=action.boot_time,
                network_upload_bps=action.network_upload_bps,
                network_download_bps=action.network_download_bps,
            )
        case SystemStorageUpdateAction():
            return replace(
                state,
                disk_total_bytes=action.disk_total_bytes,
                disk_used_bytes=action.disk_used_bytes,
                disk_percent=action.disk_percent,
            )
        case _:
            return state
