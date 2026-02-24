# ruff: noqa: D100, D101
from __future__ import annotations

from enum import StrEnum, auto

from immutable import Immutable
from redux import BaseAction


class SensorsAction(BaseAction): ...


class Sensor(StrEnum):
    TEMPERATURE = auto()
    LIGHT = auto()


class SensorsReportReadingAction(SensorsAction):
    sensor: Sensor
    reading: float
    timestamp: float


class SensorState(Immutable):
    value: float | None = None


class SensorsState(Immutable):
    temperature: SensorState = SensorState(value=None)
    light: SensorState = SensorState(value=None)
