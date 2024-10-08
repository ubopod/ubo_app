# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from ubo_app.store.operations import InputDescription


class CameraAction(BaseAction): ...


class CameraStartViewfinderAction(CameraAction):
    pattern: str | None


class CameraReportBarcodeAction(CameraAction):
    codes: list[str]


class CameraEvent(BaseEvent): ...


class CameraStartViewfinderEvent(CameraEvent):
    pattern: str | None


class CameraStopViewfinderEvent(CameraEvent):
    id: str | None


class CameraState(Immutable):
    current: InputDescription | None = None
    is_viewfinder_active: bool
    queue: list[InputDescription]
