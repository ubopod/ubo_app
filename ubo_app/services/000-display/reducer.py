# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.display import (
    DisplayAction,
    DisplayPauseAction,
    DisplayRedrawAction,
    DisplayRedrawEvent,
    DisplayState,
)

Action = InitAction | DisplayAction


def reducer(
    state: DisplayState | None,
    action: Action,
) -> ReducerResult[DisplayState, None, DisplayRedrawEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return DisplayState()
        raise InitializationActionError(action)

    match action:
        case DisplayPauseAction():
            return replace(state, is_paused=True)

        case DisplayRedrawAction():
            return CompleteReducerResult(
                state=replace(state, is_paused=False),
                events=[DisplayRedrawEvent()],
            )

        case _:
            return state
