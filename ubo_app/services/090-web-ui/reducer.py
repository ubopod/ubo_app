# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from redux import InitAction, InitializationActionError

from ubo_app.store.operations import (
    InputAction,
    InputDemandAction,
    InputResolveAction,
)
from ubo_app.store.services.web_ui import WebUIState

if TYPE_CHECKING:
    from redux import ReducerResult


def reducer(
    state: WebUIState | None,
    action: InputAction,
) -> WebUIState | ReducerResult[WebUIState, None, None]:
    if state is None:
        if isinstance(action, InitAction):
            return WebUIState(active_inputs=[])
        raise InitializationActionError(action)

    if isinstance(action, InputDemandAction):
        return replace(
            state,
            active_inputs=[*state.active_inputs, action.description],
        )

    if isinstance(action, InputResolveAction):
        return replace(
            state,
            active_inputs=[
                description
                for description in state.active_inputs
                if description.id != action.id
            ],
        )

    return state
