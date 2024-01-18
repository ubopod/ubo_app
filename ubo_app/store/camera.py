# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from redux import BaseAction, BaseEvent, Immutable


class CameraAction(BaseAction):
    ...


class CameraStartViewfinderAction(CameraAction):
    barcode_pattern: str | None


class CameraStopViewfinderAction(CameraAction):
    ...


class CameraBarcodeAction(CameraAction):
    code: str
    match: dict[str, str | None]


class CameraEvent(BaseEvent):
    ...


class CameraStartViewfinderEvent(CameraEvent):
    barcode_pattern: str | None


class CameraStopViewfinderEvent(CameraEvent):
    ...


class CameraState(Immutable):
    is_viewfinder_active: bool
