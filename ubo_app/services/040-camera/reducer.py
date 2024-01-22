# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.camera import (
    CameraAction,
    CameraEvent,
    CameraStartViewfinderAction,
    CameraStartViewfinderEvent,
    CameraState,
    CameraStopViewfinderAction,
    CameraStopViewfinderEvent,
)
from ubo_app.store.services.keypad import Key, KeypadAction

Action = InitAction | CameraAction


def reducer(
    state: CameraState | None,
    action: Action,
) -> ReducerResult[CameraState, Action, CameraEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return CameraState(
                is_viewfinder_active=False,
            )
        raise InitializationActionError(action)

    if isinstance(action, CameraStartViewfinderAction):
        return CompleteReducerResult(
            state=replace(state, is_viewfinder_active=True),
            events=[
                CameraStartViewfinderEvent(
                    barcode_pattern=action.barcode_pattern,
                ),
            ],
        )

    if isinstance(action, CameraStopViewfinderAction):
        return CompleteReducerResult(
            state=replace(state, is_viewfinder_active=False),
            events=[
                CameraStopViewfinderEvent(),
            ],
        )

    if isinstance(action, KeypadAction):  # noqa: SIM102
        if action.key == Key.BACK:
            return CompleteReducerResult(
                state=replace(state),
                actions=[
                    CameraStopViewfinderAction(),
                ],
            )

    return state
