# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.input.types import (
    InputAction,
    InputCancelAction,
    InputDemandAction,
    InputResolveAction,
    WebUIInputDescription,
)
from ubo_app.store.services.notifications import (
    NotificationsAction,
    NotificationsClearByIdAction,
)
from ubo_app.store.services.web_ui import (
    WebUIInitializeEvent,
    WebUIState,
    WebUIStopEvent,
)

if TYPE_CHECKING:
    from redux import ReducerResult

DispatchAction = InputCancelAction | NotificationsAction


def reducer(
    state: WebUIState | None,
    action: InputAction,
) -> ReducerResult[
    WebUIState,
    DispatchAction,
    WebUIInitializeEvent | WebUIStopEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            return WebUIState(active_inputs=[])
        raise InitializationActionError(action)

    match action:
        case InputDemandAction(description=WebUIInputDescription() as description):
            return CompleteReducerResult(
                state=replace(
                    state,
                    active_inputs=[*state.active_inputs, description],
                ),
                events=[WebUIInitializeEvent(description=description)],
            )

        case InputResolveAction(id=id):
            new_active_inputs = [
                description
                for description in state.active_inputs
                if description.id != id
            ]
            should_dispatch_stop_event = (
                len(state.active_inputs) > 0 and len(new_active_inputs) == 0
            )
            return CompleteReducerResult(
                state=replace(
                    state,
                    active_inputs=new_active_inputs,
                ),
                actions=[NotificationsClearByIdAction(id=f'web_ui:pending:{id}')],
                events=[WebUIStopEvent()] if should_dispatch_stop_event else [],
            )

        case _:
            return state
