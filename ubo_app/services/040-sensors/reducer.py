"""Sensors reducer."""

from __future__ import annotations

from dataclasses import replace

from redux import (
    BaseEvent,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.sensors import (
    Sensor,
    SensorsAction,
    SensorsReportDeviceReadingsAction,
    SensorsReportReadingAction,
    SensorsScanAction,
    SensorsScanCompletedAction,
    SensorsScanEvent,
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

    match action:
        case SensorsReportReadingAction(sensor=Sensor.TEMPERATURE):
            return replace(state, temperature=SensorState(value=action.reading))
        case SensorsReportReadingAction(sensor=Sensor.LIGHT):
            return replace(state, light=SensorState(value=action.reading))
        case SensorsScanAction():
            # A second scan while one is running would rebuild `ACTIVE_SENSORS`
            # underneath the first and touch the I²C bus concurrently. The
            # Refresh row stays pressable; it just does nothing until the
            # current scan reports back.
            if state.is_scanning:
                return state
            return CompleteReducerResult(
                state=replace(state, is_scanning=True),
                events=[SensorsScanEvent()],
            )
        case SensorsScanCompletedAction(devices=None):
            # The scan failed. Clearing `is_scanning` still matters — it is what
            # stops Refresh being inert until a reboot — but replacing the
            # devices would turn a transient bus error into a lost registry:
            # every entity retired in Home Assistant and an empty list
            # persisted over the real one.
            return replace(state, is_scanning=False)
        case SensorsScanCompletedAction():
            return replace(
                state,
                is_scanning=False,
                devices={device.id: device for device in action.devices or ()},
            )
        case SensorsReportDeviceReadingsAction():
            device = state.devices.get(action.device_id)
            if device is None:
                return state
            return replace(
                state,
                devices={
                    **state.devices,
                    device.id: replace(device, entities=action.entities),
                },
            )
        case _:
            return state
