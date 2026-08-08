# ruff: noqa: D100, D101
from __future__ import annotations

from dataclasses import field
from enum import StrEnum, auto

from immutable import Immutable
from redux import BaseAction, BaseEvent


class SensorsAction(BaseAction): ...


class SensorsEvent(BaseEvent): ...


class Sensor(StrEnum):
    TEMPERATURE = auto()
    LIGHT = auto()


class SensorStatus(StrEnum):
    ACTIVE = auto()
    ERROR = auto()
    UNSUPPORTED = auto()
    AMBIGUOUS = auto()


class SensorsReportReadingAction(SensorsAction):
    sensor: Sensor
    reading: float
    timestamp: float


class SensorEntityReading(Immutable):
    """One reading, carrying enough metadata to render itself.

    The descriptive fields are copied from the sensor registry's
    ``EntityDefinition`` at dispatch time. They are redundant in-process, but
    the registry never leaves the device, so a remote client that only sees
    this state slice has no other way to learn a reading's unit or label.
    """

    key: str
    value: float | None = None
    name: str = ''
    unit: str | None = None
    device_class: str | None = None
    precision: int | None = None


class SensorDeviceState(Immutable):
    id: str
    definition_id: str
    label: str
    address: int
    is_builtin: bool
    status: SensorStatus
    entities: tuple[SensorEntityReading, ...] = ()


class SensorsScanAction(SensorsAction): ...


class SensorsScanEvent(SensorsEvent): ...


class SensorsScanCompletedAction(SensorsAction):
    # `None` means the scan failed: stop scanning, but keep the devices we
    # already know about. An empty tuple is the *successful* "nothing on the
    # bus" answer, and the two must not be confused — see the reducer.
    devices: tuple[SensorDeviceState, ...] | None = None


class SensorsReportDeviceReadingsAction(SensorsAction):
    device_id: str
    entities: tuple[SensorEntityReading, ...]
    timestamp: float


class SensorState(Immutable):
    value: float | None = None


class SensorsState(Immutable):
    temperature: SensorState = SensorState(value=None)
    light: SensorState = SensorState(value=None)
    devices: dict[str, SensorDeviceState] = field(default_factory=dict)
    is_scanning: bool = False
