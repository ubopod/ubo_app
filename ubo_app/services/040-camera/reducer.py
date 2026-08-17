# ruff: noqa: D100, D103
from __future__ import annotations

import functools
import re
import time

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.core.callback_registry import register_auto_callback
from ubo_app.store.input.types import (
    InputAction,
    InputCancelAction,
    InputDemandAction,
    InputMethod,
    InputProvideAction,
    InputResolveAction,
    InputResult,
    QRCodeInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.camera import (
    CameraAction,
    CameraDetectAction,
    CameraDetectAdvertiseEvent,
    CameraDetectedEvent,
    CameraDetectEvent,
    CameraEvent,
    CameraInstallDriverAction,
    CameraInstallDriverEvent,
    CameraRegisterRemoteAction,
    CameraReportBarcodeAction,
    CameraReportImageAction,
    CameraReportImageEvent,
    CameraRestoreDefaultAction,
    CameraRestoreDefaultEvent,
    CameraSetAvailableCamerasAction,
    CameraSetIndexAction,
    CameraSetSelectedSourceAction,
    CameraSource,
    CameraSourceKind,
    CameraStartViewfinderAction,
    CameraStartViewfinderEvent,
    CameraState,
)
from ubo_app.store.services.keypad import KeypadKeyPressAction
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDispatchItem,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.utils.persistent_store import read_from_persistent_store

Action = InitAction | CameraAction | InputAction | KeypadKeyPressAction
DispatchAction = (
    NotificationsAddAction | NotificationsClearByIdAction | InputResolveAction
)


def prompt_notification(description: QRCodeInputDescription) -> NotificationsAddAction:
    return NotificationsAddAction(
        notification=Notification(
            id=f'camera:qrcode:{description.id}',
            icon='󰄀󰐲',
            title=description.title or 'QR Code',
            content=f'[size=18dp]{description.prompt}[/size]',
            display_type=NotificationDisplayType.STICKY,
            is_read=True,
            extra_information=description.instructions,
            expiration_timestamp=time.time(),
            color='#ffffff',
            actions=[
                NotificationDispatchItem(
                    # A demand without a pattern only wants a snapshot (e.g.
                    # the assistant's vision tool), not a code to scan.
                    label='Scan QR code' if description.pattern else 'Take a photo',
                    store_action=CameraStartViewfinderAction(
                        pattern=description.pattern,
                    ),
                    icon='󰄀',
                    close_notification=False,
                ),
            ],
            show_dismiss_action=False,
            dismiss_on_close=True,
            on_close_id=register_auto_callback(
                functools.partial(
                    store.dispatch,
                    InputCancelAction(id=description.id),
                ),
            ),
        ),
    )


def pop_queue(
    state: CameraState,
    *,
    actions: list[DispatchAction] | None = None,
    events: list[CameraEvent] | None = None,
) -> ReducerResult[
    CameraState,
    DispatchAction,
    CameraEvent,
]:
    if len(state.queue) == 0:
        msg = 'Cannot pop from an empty queue in CameraState.'
        raise ValueError(msg)

    actions = actions or []
    events = events or []

    # Clear the on-screen QR notification (clearing it also pops its
    # ``NotificationStackItem`` via ``StackPopNotificationAction``).
    # Intentionally do NOT dispatch ``StackPopAction`` here — that would
    # blindly pop the top of stack, which is only the viewfinder in the
    # success/scan path. When the cancel comes from ``on_close_id``
    # (user pressed back on the notification, or back-out of the
    # viewfinder via the camera setup's ``_handle_stack_changed``), the
    # top of stack is the menu the user is returning to, and popping
    # that would over-pop one level. The viewfinder, when open and the
    # input is being *provided* (scan success), is closed by the
    # ``InputProvideEvent`` handler in ``services/040-camera/setup.py``.
    actions.append(
        NotificationsClearByIdAction(id=f'camera:qrcode:{state.queue[0].id}'),
    )
    _, *queue = state.queue
    if queue:
        actions.append(prompt_notification(queue[0]))
    return CompleteReducerResult(
        state=state(queue=queue),
        actions=actions,
        events=events,
    )


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


def _ensure_selection_valid(
    available: tuple[CameraSource, ...],
    selected_source_id: str,
) -> str:
    """Keep the current selection if still available, else pick the first."""
    if not available:
        return selected_source_id
    if any(source.id == selected_source_id for source in available):
        return selected_source_id
    return available[0].id


def _merge_remote_registration(
    pending: tuple[CameraSource, ...],
    incoming: CameraSource,
) -> tuple[CameraSource, ...]:
    """Add or update a remote registration in `pending_remote_registrations`."""
    return (*tuple(s for s in pending if s.id != incoming.id), incoming)


def reducer(
    state: CameraState | None,
    action: Action,
) -> ReducerResult[
    CameraState,
    DispatchAction,
    CameraEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            return CameraState(
                queue=[],
                selected_source_id=_resolve_initial_source_id(),
            )
        raise InitializationActionError(action)

    match action:
        case InputDemandAction(description=QRCodeInputDescription() as description):
            return CompleteReducerResult(
                state=state(queue=[*state.queue, description]),
                actions=[] if state.queue else [prompt_notification(description)],
            )

        case InputResolveAction(id=id):
            if state.queue and state.queue[0].id == id:
                return pop_queue(state)
            return state(
                queue=[
                    description for description in state.queue if description.id != id
                ],
            )

        case CameraInstallDriverAction(make=make, model=model, variant=variant):
            return CompleteReducerResult(
                state=state,
                events=[
                    CameraInstallDriverEvent(
                        make=make,
                        model=model,
                        variant=variant,
                    ),
                ],
            )

        case CameraRestoreDefaultAction():
            return CompleteReducerResult(
                state=state,
                events=[CameraRestoreDefaultEvent()],
            )

        case CameraStartViewfinderAction(pattern=pattern):
            return CompleteReducerResult(
                state=state,
                events=[
                    CameraStartViewfinderEvent(
                        pattern=pattern,
                        source_id=state.selected_source_id,
                    ),
                ],
            )

        case CameraSetIndexAction(index=index):
            return state(selected_source_id=f'local:{index}')

        case CameraSetSelectedSourceAction(source_id=source_id):
            return state(selected_source_id=source_id)

        case CameraRegisterRemoteAction(source_id=source_id, label=label):
            registration = CameraSource(
                id=source_id,
                label=label,
                kind=CameraSourceKind.REMOTE,
            )
            return state(
                pending_remote_registrations=_merge_remote_registration(
                    state.pending_remote_registrations,
                    registration,
                ),
            )

        case CameraSetAvailableCamerasAction(available_cameras=available_cameras):
            available = tuple(available_cameras)
            return state(
                available_cameras=available,
                selected_source_id=_ensure_selection_valid(
                    available,
                    state.selected_source_id,
                ),
                pending_remote_registrations=(),
            )

        case CameraDetectAction():
            # Clear staging so a fresh detection cycle starts from a known
            # state, then fan out: CameraDetectEvent triggers the local
            # hardware probe, CameraDetectAdvertiseEvent invites remote
            # clients to (re-)register.
            return CompleteReducerResult(
                state=state(pending_remote_registrations=()),
                events=[CameraDetectEvent(), CameraDetectAdvertiseEvent()],
            )

        case CameraDetectedEvent(available_cameras=available_cameras):
            available = tuple(available_cameras)
            return state(
                available_cameras=available,
                selected_source_id=_ensure_selection_valid(
                    available,
                    state.selected_source_id,
                ),
                pending_remote_registrations=(),
            )

        case CameraReportBarcodeAction(codes=codes) if state.queue:
            if state.queue[0].pattern:
                for code in codes:
                    match_ = re.match(state.queue[0].pattern, code)
                    if match_:
                        return CompleteReducerResult(
                            state=state,
                            actions=[
                                InputProvideAction(
                                    id=state.queue[0].id,
                                    value=code,
                                    result=InputResult(
                                        data={
                                            key.rstrip('_'): value
                                            for key, value in match_.groupdict().items()
                                            if value
                                        },
                                        files={},
                                        method=InputMethod.CAMERA,
                                    ),
                                ),
                            ],
                        )
            else:
                return CompleteReducerResult(
                    state=state,
                    actions=[
                        InputProvideAction(
                            id=state.queue[0].id,
                            value=codes[0] if len(codes) > 0 else '',
                            result=None,
                        ),
                    ],
                )
            return state

        case CameraReportBarcodeAction(codes=codes):
            return state

        case CameraReportImageAction():
            # Remote camera sources (iPhone, web) can only dispatch actions
            # over gRPC; the corresponding event is emitted here so the
            # existing `_handle_report_image` subscriber can decode QR codes
            # and forward the frame to the viewfinder display.
            return CompleteReducerResult(
                state=state,
                events=[
                    CameraReportImageEvent(
                        timestamp=action.timestamp,
                        data=action.data,
                        width=action.width,
                        height=action.height,
                        source_id=action.source_id,
                    ),
                ],
            )

        case _:
            return state
