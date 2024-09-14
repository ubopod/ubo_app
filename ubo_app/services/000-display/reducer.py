# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    InitAction,
    InitializationActionError,
)

from ubo_app.store.services.display import (
    DisplayAction,
    DisplayPauseAction,
    DisplayResumeAction,
    DisplayState,
)

Action = InitAction | DisplayAction


def reducer(
    state: DisplayState | None,
    action: Action,
) -> DisplayState:
    if state is None:
        if isinstance(action, InitAction):
            return DisplayState()
        raise InitializationActionError(action)

    if isinstance(action, DisplayPauseAction):
        return replace(state, is_paused=True)

    if isinstance(action, DisplayResumeAction):
        return replace(state, is_paused=False)

    return state
