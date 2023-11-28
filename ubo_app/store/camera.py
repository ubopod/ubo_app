# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from redux import BaseAction, BaseEvent, Immutable


class CameraAction(BaseAction):
    ...


class CameraStartViewfinderActionPayload(Immutable):
    barcode_pattern: str | None


class CameraStartViewfinderAction(CameraAction):
    payload: CameraStartViewfinderActionPayload


class CameraStopViewFinderAction(CameraAction):
    payload: None = None


class CameraBarcodeActionPayload(Immutable):
    code: str
    match: dict[str, str | None]


class CameraBarcodeAction(CameraAction):
    payload: CameraBarcodeActionPayload


class CameraEvent(BaseEvent):
    ...


class CameraStartViewfinderEventPayload(Immutable):
    barcode_pattern: str | None


class CameraStartViewfinderEvent(CameraEvent):
    payload: CameraStartViewfinderEventPayload


class CameraStopViewfinderEvent(CameraEvent):
    payload: None = None


class CameraState(Immutable):
    is_viewfinder_active: bool
