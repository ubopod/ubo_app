"""Input reducer."""

from __future__ import annotations

from redux import CompleteReducerResult, ReducerResult

from .types import (
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
    match action:
        case InputProvideAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    InputProvideEvent(
                        id=action.id,
                        value=action.value,
                        result=action.result,
                    ),
                ],
            )

        case InputCancelAction():
            return CompleteReducerResult(
                state=state,
                events=[InputCancelEvent(id=action.id)],
            )

        case _:
            return None
