# ruff: noqa: D100, D103
from __future__ import annotations

import datetime
import functools
import re
from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.input.types import (
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
    CameraEvent,
    CameraReportBarcodeAction,
    CameraStartViewfinderAction,
    CameraStartViewfinderEvent,
    CameraState,
    CameraStopViewfinderEvent,
)
from ubo_app.store.services.keypad import KeypadKeyPressAction
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDispatchItem,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)

Action = InitAction | CameraAction | InputDemandAction | KeypadKeyPressAction
DispatchAction = (
    NotificationsAddAction | NotificationsClearByIdAction | InputResolveAction
)


def prompt_notification(description: QRCodeInputDescription) -> NotificationsAddAction:
    return NotificationsAddAction(
        notification=Notification(
            id=f'camera:qrcode:{description.id}',
            icon='󰄀󰐲',
            title='QR Code',
            content=f'[size=18dp]{description.prompt}[/size]',
            display_type=NotificationDisplayType.STICKY,
            is_read=True,
            extra_information=description.instructions,
            expiration_timestamp=datetime.datetime.now(tz=datetime.UTC),
            color='#ffffff',
            actions=[
                NotificationDispatchItem(
                    store_action=CameraStartViewfinderAction(
                        pattern=description.pattern,
                    ),
                    icon='󰄀',
                    close_notification=False,
                ),
            ],
            show_dismiss_action=False,
            dismiss_on_close=True,
            on_close=functools.partial(
                store.dispatch,
                InputCancelAction(id=description.id),
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
    events.append(CameraStopViewfinderEvent())

    actions.append(
        NotificationsClearByIdAction(id=f'camera:qrcode:{state.queue[0].id}'),
    )
    _, *queue = state.queue
    if queue:
        actions.append(prompt_notification(queue[0]))
    return CompleteReducerResult(
        state=replace(state, queue=queue),
        actions=actions,
        events=events,
    )


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
            return CameraState(queue=[])
        raise InitializationActionError(action)

    if isinstance(action, InputDemandAction) and isinstance(
        action.description,
        QRCodeInputDescription,
    ):
        return CompleteReducerResult(
            state=replace(state, queue=[*state.queue, action.description]),
            actions=[] if state.queue else [prompt_notification(action.description)],
        )

    if isinstance(action, InputResolveAction):
        if state.queue and state.queue[0].id == action.id:
            return pop_queue(state)
        return replace(
            state,
            queue=[
                description
                for description in state.queue
                if description.id != action.id
            ],
        )

    if isinstance(action, CameraStartViewfinderAction):
        return CompleteReducerResult(
            state=replace(state),
            events=[CameraStartViewfinderEvent(pattern=action.pattern)],
        )

    if isinstance(action, CameraReportBarcodeAction) and state.queue:
        for code in action.codes:
            if state.queue[0].pattern:
                match = re.match(state.queue[0].pattern, code)
                if match:
                    return CompleteReducerResult(
                        state=state,
                        actions=[
                            InputProvideAction(
                                id=state.queue[0].id,
                                value=code,
                                result=InputResult(
                                    data={
                                        key.rstrip('_'): value
                                        for key, value in match.groupdict().items()
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
                            value=code,
                            result=None,
                        ),
                    ],
                )

            return state

    return state
