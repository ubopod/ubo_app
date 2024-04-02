"""Sensors reducer."""

from __future__ import annotations

from dataclasses import replace

from redux import BaseEvent, InitAction, InitializationActionError, ReducerResult

from ubo_app.store.services.sensors import (
    Sensor,
    SensorsAction,
    SensorsReportReadingAction,
    SensorsState,
    SensorState,
)

Action = InitAction | SensorsAction


def reducer(
    state: SensorsState | None,
    action: Action,
) -> ReducerResult[SensorsState, Action, BaseEvent]:
    """Sensors reducer."""
    if state is None:
        if isinstance(action, InitAction):
            return SensorsState()
        raise InitializationActionError(action)

    if isinstance(action, SensorsReportReadingAction):
        if action.sensor == Sensor.TEMPERATURE:
            return replace(state, temperature=SensorState(value=action.reading))
        if action.sensor == Sensor.LIGHT:
            return replace(state, light=SensorState(value=action.reading))

    return state
