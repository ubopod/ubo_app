# ruff: noqa: D100, D101, D102, D103, D104, D107
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


def pop_queue(state: CameraState) -> CameraState:
    if len(state.queue) > 0:
        input_description, *queue = state.queue
        return replace(state, current=input_description, queue=queue)
    return replace(
        state,
        is_viewfinder_active=False,
        current=None,
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
            return CameraState(is_viewfinder_active=False, queue=[])
        raise InitializationActionError(action)

    if isinstance(action, InputDemandAction) and action.method is InputMethod.CAMERA:
        if state.is_viewfinder_active:
            return replace(
                state,
                queue=[
                    *state.queue,
                    action.description,
                ],
            )
        return CompleteReducerResult(
            state=replace(
                state,
                current=action.description,
            ),
            actions=[
                NotificationsAddAction(
                    notification=Notification(
                        id='camera:qrcode',
                        icon='󰄀󰐲',
                        title='QR Code',
                        content=f'[size=18dp]{action.description.prompt}[/size]',
                        display_type=NotificationDisplayType.STICKY,
                        is_read=True,
                        extra_information=action.description.extra_information,
                        expiration_timestamp=datetime.datetime.now(tz=datetime.UTC),
                        color='#ffffff',
                        actions=[
                            NotificationDispatchItem(
                                store_action=CameraStartViewfinderAction(
                                    pattern=action.description.pattern,
                                ),
                                icon='󰄀',
                                close_notification=False,
                            ),
                        ],
                        show_dismiss_action=False,
                        dismiss_on_close=True,
                        on_close=functools.partial(
                            store.dispatch,
                            InputCancelAction(id=action.description.id),
                        ),
                    ),
                ),
            ],
        )

    if isinstance(action, InputResolveAction | InputCancelAction):
        if state.current and state.current.id == action.id:
            return CompleteReducerResult(
                state=pop_queue(state),
                actions=[NotificationsClearByIdAction(id='camera:qrcode')],
                events=[CameraStopViewfinderEvent(id=state.current.id)],
            )
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
            state=replace(
                state,
                is_viewfinder_active=True,
            ),
            events=[CameraStartViewfinderEvent(pattern=action.pattern)],
        )

    if isinstance(action, CameraReportBarcodeAction) and state.current:
        for code in action.codes:
            if state.current.pattern:
                match = re.match(state.current.pattern, code)
                if match:
                    return CompleteReducerResult(
                        state=pop_queue(state),
                        actions=[
                            InputProvideAction(
                                id=state.current.id,
                                value=code,
                                data={
                                    key.rstrip('_'): value
                                    for key, value in match.groupdict().items()
                                },
                            ),
                            NotificationsClearByIdAction(id='camera:qrcode'),
                        ],
                        events=[
                            CameraStopViewfinderEvent(id=None),
                        ],
                    )
            else:
                return CompleteReducerResult(
                    state=pop_queue(state),
                    actions=[
                        InputProvideAction(
                            id=state.current.id,
                            value=code,
                            data=None,
                        ),
                    ],
                    events=[
                        CameraStopViewfinderEvent(id=None),
                    ],
                )

            return state

    return state
