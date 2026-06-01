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


class CameraSourceKind(StrEnum):
    """Whether a camera source is hardware on this device or a remote client."""

    LOCAL = 'local'
    REMOTE = 'remote'


if TYPE_CHECKING:
    from ubo_app.store.input.types import QRCodeInputDescription


class CameraSource(Immutable):
    """A selectable camera source.

    Local sources are USB / picamera devices probed by the camera service;
    remote sources are clients (iOS, web, etc.) that registered themselves
    via `CameraRegisterRemoteAction` after a `CameraDetectAdvertiseEvent`.
    """

    id: str  # 'local:<index>' or 'remote:<client-uuid>'
    label: str
    kind: CameraSourceKind


class CameraAction(BaseAction): ...


class CameraStartViewfinderAction(CameraAction):
    pattern: str | None


class CameraReportBarcodeAction(CameraAction):
    codes: list[str]


class CameraReportImageAction(CameraAction):
    """A single camera frame pushed by a remote camera source over gRPC.

    Remote clients (iOS, web, etc.) cannot dispatch events directly — events
    are emitted only from reducers. So a remote source dispatches this action
    with the frame payload; the reducer translates it into a
    `CameraReportImageEvent` that downstream subscribers consume (QR decode,
    display mirror).
    """

    timestamp: float
    data: bytes
    width: int
    height: int
    source_id: str = ''


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
    source_id: str = ''  # which source should start capturing; empty == any


class CameraReportImageEvent(CameraEvent):
    """A single camera frame.

    Dispatched both by the local capture loop and by remote clients pushing
    frames over gRPC. The `source_id` field lets the Pi-side handler accept
    only frames from the currently selected source.
    """

    timestamp: float
    data: bytes
    width: int
    height: int
    source_id: str = ''


class CameraStopViewfinderEvent(CameraEvent): ...


class CameraSetIndexAction(CameraAction):
    """Deprecated shim — prefer `CameraSetSelectedSourceAction`.

    Kept so that older clients dispatching this action still work. The
    reducer translates `index=N` to `selected_source_id='local:N'`.
    """

    index: int


class CameraSetSelectedSourceAction(CameraAction):
    """Select which source (local or remote) feeds the viewfinder."""

    source_id: str


class CameraDetectAction(CameraAction):
    """Action to trigger camera detection."""


class CameraDetectAdvertiseEvent(CameraEvent):
    """Broadcast when detection starts.

    Subscribed clients (iOS, web, etc.) should respond with a
    `CameraRegisterRemoteAction` if they can provide a camera stream.
    """


class CameraRegisterRemoteAction(CameraAction):
    """Dispatched by a remote client in response to `CameraDetectAdvertiseEvent`."""

    source_id: str
    label: str


class CameraSetAvailableCamerasAction(CameraAction):
    """Set the merged local + remote camera source list."""

    available_cameras: list[CameraSource]


class CameraDetectEvent(CameraEvent):
    """Event fired to trigger camera detection."""


class CameraDetectedEvent(CameraEvent):
    """Event fired when cameras are detected."""

    available_cameras: list[CameraSource]


class CameraReinitializeEvent(CameraEvent):
    """Event to trigger camera reinitialization with new index."""


def _resolve_initial_source_id() -> str:
    """Pick the initial selected-source id, migrating from the old int key.

    Older releases persisted `camera_selected_index` (int). Newer state lives
    under `camera_selected_source_id` (str). If only the old key is present,
    we synthesise `local:<index>` so the user's previous choice survives.
    """
    new_value = read_from_persistent_store(
        'camera_selected_source_id',
        default=None,
        output_type=str,
    )
    if new_value:
        return new_value
    legacy_index = read_from_persistent_store(
        'camera_selected_index',
        default=None,
        output_type=int,
    )
    if legacy_index is not None:
        return f'local:{legacy_index}'
    return 'local:0'


class CameraState(Immutable):
    queue: list[QRCodeInputDescription]
    selected_source_id: str = _resolve_initial_source_id()
    available_cameras: tuple[CameraSource, ...] = ()
    pending_remote_registrations: tuple[CameraSource, ...] = ()
    camera_type: CameraType = read_from_persistent_store(
        'camera_type',
        default=CameraType.DEFAULT,
    )
