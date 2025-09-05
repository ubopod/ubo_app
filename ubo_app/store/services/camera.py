# ruff: noqa: D100, D101
from __future__ import annotations

from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from ubo_app.store.input.types import QRCodeInputDescription


class CameraAction(BaseAction): ...


class CameraStartViewfinderAction(CameraAction):
    pattern: str | None


class CameraReportBarcodeAction(CameraAction):
    codes: list[str]


class CameraEvent(BaseEvent): ...


class CameraStartViewfinderEvent(CameraEvent):
    pattern: str | None


class CameraReportImageEvent(CameraEvent):
    """Event for reporting an image from the camera."""

    timestamp: float
    data: bytes
    width: int
    height: int


class CameraStopViewfinderEvent(CameraEvent): ...


class CameraState(Immutable):
    queue: list[QRCodeInputDescription]
