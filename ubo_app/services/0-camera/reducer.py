# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.camera import (
    CameraAction,
    CameraEvent,
    CameraStartViewfinderAction,
    CameraStartViewfinderEvent,
    CameraStartViewfinderEventPayload,
    CameraState,
    CameraStopViewFinderAction,
    CameraStopViewfinderEvent,
)

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
        raise InitializationActionError

    if isinstance(action, CameraStartViewfinderAction):
        return CompleteReducerResult(
            state=replace(state, is_viewfinder_active=True),
            events=[
                CameraStartViewfinderEvent(
                    payload=CameraStartViewfinderEventPayload(
                        barcode_pattern=action.payload.barcode_pattern,
                    ),
                ),
            ],
        )

    if isinstance(action, CameraStopViewFinderAction):
        return CompleteReducerResult(
            state=replace(state, is_viewfinder_active=True),
            events=[
                CameraStopViewfinderEvent(),
            ],
        )

    return state
