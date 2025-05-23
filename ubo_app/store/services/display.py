# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class DisplayAction(BaseAction): ...


class DisplayEvent(BaseEvent): ...


class DisplayPauseAction(DisplayAction): ...


class DisplayResumeAction(DisplayAction): ...


class DisplayRerenderEvent(DisplayEvent): ...


class DisplayRenderEvent(DisplayEvent):
    timestamp: float
    data: bytes
    rectangle: tuple[int, int, int, int]
    density: float


class DisplayCompressedRenderEvent(DisplayEvent):
    timestamp: float
    compressed_data: bytes
    rectangle: tuple[int, int, int, int]
    density: float


class DisplayState(Immutable):
    is_paused: bool = False
