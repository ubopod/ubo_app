# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from enum import StrEnum, auto
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction

if TYPE_CHECKING:
    from datetime import datetime


class SensorsAction(BaseAction): ...


class Sensor(StrEnum):
    TEMPERATURE = auto()
    LIGHT = auto()


class SensorsReportReadingAction(SensorsAction):
    sensor: Sensor
    reading: float
    timestamp: datetime


class SensorState(Immutable):
    value: float | None = None


class SensorsState(Immutable):
    temperature: SensorState = SensorState(value=None)
    light: SensorState = SensorState(value=None)
