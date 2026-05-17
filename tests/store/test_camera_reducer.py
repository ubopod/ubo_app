"""Tests for the camera reducer's `CameraReportImageAction` → event pass-through.

Remote camera sources (iPhone, web) push frames over gRPC as actions; the
reducer translates them into `CameraReportImageEvent`s so downstream
subscribers (`_handle_report_image`) can decode QR codes and forward to the
viewfinder display.

NOTE: The camera service uses relative imports inside its directory, so we
add the service path to ``sys.path`` before importing the reducer — same
pattern as ``test_file_system_reducer.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from redux import CompleteReducerResult

from ubo_app.store.services.camera import (
    CameraReportImageAction,
    CameraReportImageEvent,
    CameraState,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _load_reducer() -> Callable[[CameraState, Any], Any]:
    service_dir = str(
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '040-camera',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)
    from reducer import reducer  # type: ignore[import-not-found]

    return reducer


def test_camera_report_image_action_emits_event_with_matching_fields() -> None:
    """The reducer must turn a remote frame action into a frame event."""
    state = CameraState(queue=[])
    action = CameraReportImageAction(
        timestamp=1234.5,
        data=b'\x01\x02\x03',
        width=240,
        height=240,
        source_id='remote:iphone-uuid',
    )

    result = _load_reducer()(state, action)

    assert isinstance(result, CompleteReducerResult)
    assert result.state is state  # pure pass-through, no state mutation
    events = list(result.events or [])
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, CameraReportImageEvent)
    assert event.timestamp == action.timestamp
    assert event.data == action.data
    assert event.width == action.width
    assert event.height == action.height
    assert event.source_id == action.source_id


def test_camera_report_image_action_preserves_empty_source_id() -> None:
    """Local-source actions (empty source_id) must still produce an event."""
    state = CameraState(queue=[])
    action = CameraReportImageAction(
        timestamp=0.0,
        data=b'',
        width=0,
        height=0,
        source_id='',
    )

    result = _load_reducer()(state, action)

    assert isinstance(result, CompleteReducerResult)
    events = list(result.events or [])
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, CameraReportImageEvent)
    assert event.source_id == ''
