# ruff: noqa: D100, D101
from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class CameraType(StrEnum):
    """Camera type enum."""

    DEFAULT = 'default'
    AUTOFOCUS = 'autofocus'
    FIXED_FOCUS = 'fixed-focus'

if TYPE_CHECKING:
    from ubo_app.store.input.types import QRCodeInputDescription


class CameraAction(BaseAction): ...


class CameraStartViewfinderAction(CameraAction):
    pattern: str | None


class CameraReportBarcodeAction(CameraAction):
    codes: list[str]


class CameraInstallDriverAction(CameraAction):
    """Install camera driver action."""

    make: str
    model: str
    variant: str


class CameraEvent(BaseEvent): ...


class CameraInstallDriverEvent(CameraEvent):
    """Install camera driver event."""

    make: str
    model: str
    variant: str


class CameraRestoreDefaultAction(CameraAction):
    """Restore default camera configuration action."""


class CameraRestoreDefaultEvent(CameraEvent):
    """Restore default camera configuration event."""


class CameraStartViewfinderEvent(CameraEvent):
    pattern: str | None


class CameraReportImageEvent(CameraEvent):
    """Event for reporting an image from the camera."""

    timestamp: float
    data: bytes
    width: int
    height: int


class CameraStopViewfinderEvent(CameraEvent): ...


class CameraSetIndexAction(CameraAction):
    """Action to set the selected camera index."""

    index: int


class CameraDetectAction(CameraAction):
    """Action to trigger camera detection."""


class CameraSetAvailableCamerasAction(CameraAction):
    """Action to set available cameras."""

    available_cameras: list[int]


class CameraDetectEvent(CameraEvent):
    """Event fired to trigger camera detection."""


class CameraDetectedEvent(CameraEvent):
    """Event fired when cameras are detected."""

    available_cameras: list[int]


class CameraReinitializeEvent(CameraEvent):
    """Event to trigger camera reinitialization with new index."""


class CameraState(Immutable):
    queue: list[QRCodeInputDescription]
    selected_camera_index: int = 0
    available_cameras: tuple[int, ...] = ()
    camera_type: CameraType = read_from_persistent_store(
        'camera_type',
        default=CameraType.DEFAULT,
    )
