# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class DisplayAction(BaseAction): ...


class DisplayEvent(BaseEvent): ...


class DisplayPauseAction(DisplayAction): ...


class DisplayResumeAction(DisplayAction): ...


class DisplayRenderEvent(DisplayEvent):
    data: bytes
    data_hash: int
    rectangle: tuple[int, int, int, int]


class DisplayCompressedRenderEvent(DisplayEvent):
    compressed_data: bytes
    data_hash: int
    rectangle: tuple[int, int, int, int]


class DisplayState(Immutable):
    is_paused: bool = False
