# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import re
from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.camera import (
    CameraAction,
    CameraBarcodeEvent,
    CameraEvent,
    CameraReportBarcodeAction,
    CameraStartViewfinderAction,
    CameraStartViewfinderEvent,
    CameraState,
    CameraStopViewfinderEvent,
    InputDescription,
)
from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

Action = InitAction | CameraAction


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
) -> ReducerResult[CameraState, Action, CameraEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return CameraState(is_viewfinder_active=False, queue=[])
        raise InitializationActionError(action)

    if isinstance(action, CameraStartViewfinderAction):
        if state.is_viewfinder_active:
            return replace(
                state,
                queue=[
                    *state.queue,
                    InputDescription(id=action.id, pattern=action.pattern),
                ],
            )
        return CompleteReducerResult(
            state=replace(
                state,
                is_viewfinder_active=True,
                current=InputDescription(id=action.id, pattern=action.pattern),
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
                        events=[
                            CameraBarcodeEvent(
                                id=state.current.id,
                                code=code,
                                group_dict=match.groupdict(),
                            ),
                            CameraStopViewfinderEvent(id=None),
                        ],
                    )
            else:
                return CompleteReducerResult(
                    state=pop_queue(state),
                    events=[
                        CameraBarcodeEvent(
                            id=state.current.id,
                            code=code,
                            group_dict=None,
                        ),
                        CameraStopViewfinderEvent(id=None),
                    ],
                )

            return state

    if isinstance(action, KeypadKeyPressAction):  # noqa: SIM102
        if action.key == Key.BACK and state.is_viewfinder_active:
            return CompleteReducerResult(
                state=pop_queue(state),
                events=[
                    CameraStopViewfinderEvent(
                        id=state.current.id if state.current else None,
                    ),
                ],
            )

    return state
