# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, Generic, Sequence, TypeVar

from redux import BaseAction, Immutable

if TYPE_CHECKING:
    from datetime import datetime


class SensorsAction(BaseAction):
    ...


Primitive = int | float | str | bool
SensorType = TypeVar('SensorType', bound=Primitive | Sequence[Primitive])


class Sensor(Enum):
    TEMPERATURE = auto()
    LIGHT = auto()


class SensorsReportReadingAction(SensorsAction, Generic[SensorType]):
    sensor: Sensor
    reading: SensorType
    timestamp: datetime


class SensorState(Immutable, Generic[SensorType]):
    value: SensorType | None = None


class SensorsState(Immutable):
    temperature: SensorState[float] = SensorState(value=None)
    light: SensorState[float] = SensorState(value=None)
