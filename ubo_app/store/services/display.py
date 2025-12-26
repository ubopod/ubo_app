# ruff: noqa: D100, D101
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class DisplayAction(BaseAction): ...


class DisplayEvent(BaseEvent): ...


class DisplayPauseAction(DisplayAction): ...


class DisplayResumeAction(DisplayAction): ...


class DisplayRedrawAction(DisplayAction): ...


class DisplayBlankAction(DisplayAction): ...


class DisplayUnblankAction(DisplayAction): ...


class DisplayUpdateActivityAction(DisplayAction): ...


class DisplayRedrawEvent(DisplayEvent): ...


class DisplayBlankEvent(DisplayEvent): ...


class DisplayUnblankEvent(DisplayEvent): ...


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
    is_blanked: bool = False
    last_activity_time: float | None = None
