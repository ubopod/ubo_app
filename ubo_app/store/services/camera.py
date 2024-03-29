# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class CameraAction(BaseAction): ...


class CameraStartViewfinderAction(CameraAction):
    id: str
    pattern: str | None


class CameraEvent(BaseEvent): ...


class CameraStartViewfinderEvent(CameraEvent):
    pattern: str | None


class CameraStopViewfinderEvent(CameraEvent):
    id: str | None


class CameraReportBarcodeAction(CameraAction):
    codes: list[str]


class CameraBarcodeEvent(CameraEvent):
    id: str | None
    code: str
    group_dict: dict[str, str | None] | None


class InputDescription(Immutable):
    id: str
    pattern: str | None


class CameraState(Immutable):
    current: InputDescription | None = None
    is_viewfinder_active: bool
    queue: list[InputDescription]
