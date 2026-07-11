"""Tests for the camera reducer's `CameraReportImageAction` → event pass-through.

Remote camera sources (iPhone, web) push frames over gRPC as actions; the
reducer translates them into `CameraReportImageEvent`s so downstream
subscribers (`_handle_report_image`) can decode QR codes and forward to the
viewfinder display.

NOTE: The camera service uses relative imports inside its directory, so we
add the service path to ``sys.path`` before importing the reducer — same
pattern as ``test_file_upload.py``. We also load the action/event/state
classes inside the same loader so the reducer's match-case and the test's
constructed action always reference the *same* class object, even if an
integration test in between has cleared ``sys.modules``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from redux import CompleteReducerResult

if TYPE_CHECKING:
    from collections.abc import Callable


def _import_store_types_and_reducer() -> tuple[Any, Any, Any, Callable[..., Any]]:
    """Load camera store types and the camera reducer together.

    Records sys.modules before import and cleans up newly loaded modules
    afterwards so that integration/flow tests are not affected by leftover
    module state. Returning the freshly-imported classes alongside the
    reducer guarantees both sides agree on the same class object even if
    other tests subsequently reload ``ubo_app.store.services.camera``.
    """
    modules_before = set(sys.modules)

    from ubo_app.store.services.camera import (
        CameraReportImageAction,
        CameraReportImageEvent,
        CameraState,
    )

    service_dir = str(
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '040-camera',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # type: ignore[import-not-found]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return (
        CameraReportImageAction,
        CameraReportImageEvent,
        CameraState,
        reducer,
    )


(
    CameraReportImageAction,
    CameraReportImageEvent,
    CameraState,
    reducer,
) = _import_store_types_and_reducer()


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

    result = reducer(state, action)

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

    result = reducer(state, action)

    assert isinstance(result, CompleteReducerResult)
    events = list(result.events or [])
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, CameraReportImageEvent)
    assert event.source_id == ''


def _g(name: str) -> Any:  # noqa: ANN401
    """Fetch a class the reducer imported, guaranteeing one module generation."""
    return reducer.__globals__[name]


def _qr(description_id: str, *, pattern: str | None = None) -> Any:  # noqa: ANN401
    return _g('QRCodeInputDescription')(id=description_id, pattern=pattern)


def test_none_state_init_and_raise() -> None:
    """InitAction builds state; any other action against None raises."""
    assert isinstance(reducer(None, _g('InitAction')()), CameraState)
    with pytest.raises(_g('InitializationActionError')):
        reducer(None, _g('CameraRestoreDefaultAction')())


def test_qr_demand_prompts_first_then_queues_silently() -> None:
    """The first QR demand shows a prompt; a second only queues behind it."""
    first = _qr('q1')
    result = reducer(CameraState(queue=[]), _g('InputDemandAction')(description=first))
    assert result.state.queue == [first]
    assert any(
        isinstance(action, _g('NotificationsAddAction'))
        for action in (result.actions or [])
    )

    second = _qr('q2')
    result = reducer(result.state, _g('InputDemandAction')(description=second))
    assert result.state.queue == [first, second]
    assert not result.actions


def test_resolve_head_pops_queue_and_prompts_next() -> None:
    """Resolving the active demand clears it and surfaces the next one."""
    first, second = _qr('q1'), _qr('q2')
    state = CameraState(queue=[first, second])

    result = reducer(state, _g('InputResolveAction')(id='q1'))

    assert result.state.queue == [second]
    action_types = [type(a) for a in (result.actions or [])]
    assert _g('NotificationsClearByIdAction') in action_types
    assert _g('NotificationsAddAction') in action_types


def test_resolve_non_head_filters_without_popping() -> None:
    """Resolving a queued (non-active) demand just drops it from the queue."""
    first, second = _qr('q1'), _qr('q2')
    state = CameraState(queue=[first, second])

    result = reducer(state, _g('InputResolveAction')(id='q2'))

    assert result.queue == [first]


def test_install_driver_sets_type_and_emits_event() -> None:
    """Installing a driver records the camera type and emits an install event."""
    result = reducer(
        CameraState(queue=[]),
        _g('CameraInstallDriverAction')(make='pi', model='v3', variant='autofocus'),
    )
    assert result.state.camera_type == _g('CameraType')('autofocus')
    assert any(
        isinstance(e, _g('CameraInstallDriverEvent')) for e in (result.events or [])
    )


def test_restore_default_resets_type() -> None:
    """Restoring defaults sets the DEFAULT camera type and emits an event."""
    result = reducer(CameraState(queue=[]), _g('CameraRestoreDefaultAction')())
    assert result.state.camera_type == _g('CameraType').DEFAULT
    assert any(
        isinstance(e, _g('CameraRestoreDefaultEvent')) for e in (result.events or [])
    )


def test_start_viewfinder_carries_selected_source() -> None:
    """Starting the viewfinder emits the pattern and the selected source id."""
    state = CameraState(queue=[], selected_source_id='local:1')
    result = reducer(state, _g('CameraStartViewfinderAction')(pattern='p'))
    events = list(result.events or [])
    assert len(events) == 1
    assert events[0].pattern == 'p'
    assert events[0].source_id == 'local:1'


def test_set_index_maps_to_local_source_id() -> None:
    """The deprecated index shim maps to a ``local:N`` source id."""
    result = reducer(CameraState(queue=[]), _g('CameraSetIndexAction')(index=2))
    assert result.selected_source_id == 'local:2'


def test_set_selected_source() -> None:
    """Selecting a source records its id verbatim."""
    result = reducer(
        CameraState(queue=[]),
        _g('CameraSetSelectedSourceAction')(source_id='remote:phone'),
    )
    assert result.selected_source_id == 'remote:phone'


def test_register_remote_adds_pending_registration() -> None:
    """A remote registration is staged in ``pending_remote_registrations``."""
    result = reducer(
        CameraState(queue=[]),
        _g('CameraRegisterRemoteAction')(source_id='remote:x', label='Phone'),
    )
    assert [s.id for s in result.pending_remote_registrations] == ['remote:x']


def test_set_available_cameras_keeps_valid_selection() -> None:
    """Available-camera updates keep a still-present selection and clear staging."""
    source = _g('CameraSource')(
        id='local:0',
        label='USB',
        kind=_g('CameraSourceKind').LOCAL,
    )
    state = CameraState(queue=[], selected_source_id='local:0')

    result = reducer(
        state,
        _g('CameraSetAvailableCamerasAction')(available_cameras=[source]),
    )

    assert result.selected_source_id == 'local:0'
    assert result.pending_remote_registrations == ()


def test_set_available_cameras_falls_back_when_selection_gone() -> None:
    """When the selected source disappears, the first available one is chosen."""
    source = _g('CameraSource')(
        id='local:9',
        label='USB',
        kind=_g('CameraSourceKind').LOCAL,
    )
    state = CameraState(queue=[], selected_source_id='local:0')

    result = reducer(
        state,
        _g('CameraSetAvailableCamerasAction')(available_cameras=[source]),
    )

    assert result.selected_source_id == 'local:9'


def test_detect_clears_staging_and_fans_out_events() -> None:
    """Detection clears pending remotes and emits probe + advertise events."""
    result = reducer(CameraState(queue=[]), _g('CameraDetectAction')())
    event_types = {type(e) for e in (result.events or [])}
    assert _g('CameraDetectEvent') in event_types
    assert _g('CameraDetectAdvertiseEvent') in event_types


def test_detected_event_updates_available_cameras() -> None:
    """A detected event records the available cameras and validates selection."""
    source = _g('CameraSource')(
        id='local:0',
        label='USB',
        kind=_g('CameraSourceKind').LOCAL,
    )
    result = reducer(
        CameraState(queue=[]),
        _g('CameraDetectedEvent')(available_cameras=[source]),
    )
    assert [s.id for s in result.available_cameras] == ['local:0']


def test_barcode_matching_pattern_provides_named_groups() -> None:
    """A barcode matching the active pattern resolves the input with its groups."""
    state = CameraState(queue=[_qr('q1', pattern=r'(?P<code>\d+)')])

    result = reducer(state, _g('CameraReportBarcodeAction')(codes=['abc', '4321']))

    provides = [
        a for a in (result.actions or []) if isinstance(a, _g('InputProvideAction'))
    ]
    assert len(provides) == 1
    assert provides[0].value == '4321'
    assert provides[0].result.data == {'code': '4321'}


def test_barcode_not_matching_pattern_is_ignored() -> None:
    """A barcode that fails the active pattern leaves the queue untouched."""
    state = CameraState(queue=[_qr('q1', pattern=r'^\d+$')])

    result = reducer(state, _g('CameraReportBarcodeAction')(codes=['not-a-number']))

    assert result is state


def test_barcode_without_pattern_provides_raw_value() -> None:
    """With no pattern, the first scanned code resolves the input directly."""
    state = CameraState(queue=[_qr('q1', pattern=None)])

    result = reducer(state, _g('CameraReportBarcodeAction')(codes=['hello']))

    provides = [
        a for a in (result.actions or []) if isinstance(a, _g('InputProvideAction'))
    ]
    assert len(provides) == 1
    assert provides[0].value == 'hello'
    assert provides[0].result is None


def test_barcode_with_empty_queue_is_ignored() -> None:
    """A barcode with nothing awaiting input is a no-op."""
    state = CameraState(queue=[])
    assert reducer(state, _g('CameraReportBarcodeAction')(codes=['x'])) is state


def test_unknown_action_returns_state_unchanged() -> None:
    """An action matching no case leaves the state untouched."""
    state = CameraState(queue=[])
    assert reducer(state, _g('InitAction')()) is state


def test_set_available_empty_keeps_current_selection() -> None:
    """An empty available list leaves the current selection in place."""
    state = CameraState(queue=[], selected_source_id='local:0')
    result = reducer(
        state,
        _g('CameraSetAvailableCamerasAction')(available_cameras=[]),
    )
    assert result.selected_source_id == 'local:0'


def test_pop_queue_on_empty_queue_raises() -> None:
    """The pop_queue guard refuses to pop an empty queue."""
    pop_queue = reducer.__globals__['pop_queue']
    with pytest.raises(ValueError, match='empty queue'):
        pop_queue(CameraState(queue=[]))
