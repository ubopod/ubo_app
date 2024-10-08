"""Input reducer."""

from __future__ import annotations

from redux import CompleteReducerResult, ReducerResult

from ubo_app.store.operations import (
    InputAction,
    InputCancelAction,
    InputCancelEvent,
    InputProvideAction,
    InputProvideEvent,
    InputResolveEvent,
)


def reducer(
    state: None,
    action: InputAction,
) -> ReducerResult[None, None, InputResolveEvent]:
    """Input reducer."""
    if isinstance(action, InputProvideAction):
        return CompleteReducerResult(
            state=state,
            events=[
                InputProvideEvent(
                    id=action.id,
                    value=action.value,
                    data=action.data,
                ),
            ],
        )

    if isinstance(action, InputCancelAction):
        return CompleteReducerResult(
            state=state,
            events=[InputCancelEvent(id=action.id)],
        )

    return None
