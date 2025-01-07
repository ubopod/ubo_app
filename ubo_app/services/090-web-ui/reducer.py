# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.input.types import (
    InputAction,
    InputCancelAction,
    InputDemandAction,
    InputMethod,
    InputResolveAction,
)
from ubo_app.store.services.notifications import (
    NotificationsAction,
    NotificationsClearByIdAction,
)
from ubo_app.store.services.web_ui import WebUICheckHotspotEvent, WebUIState

if TYPE_CHECKING:
    from redux import ReducerResult

DispatchAction = InputCancelAction | NotificationsAction


def reducer(
    state: WebUIState | None,
    action: InputAction,
) -> WebUIState | ReducerResult[WebUIState, DispatchAction, WebUICheckHotspotEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return WebUIState(active_inputs=[])
        raise InitializationActionError(action)

    if (
        isinstance(action, InputDemandAction)
        and action.method is InputMethod.WEB_DASHBOARD
    ):
        return CompleteReducerResult(
            state=replace(
                state,
                active_inputs=[*state.active_inputs, action.description],
            ),
            events=[WebUICheckHotspotEvent(description=action.description)],
        )
    if isinstance(action, InputResolveAction | InputCancelAction):
        return CompleteReducerResult(
            state=replace(
                state,
                active_inputs=(
                    new_active_inputs := [
                        description
                        for description in state.active_inputs
                        if description.id != action.id
                    ]
                ),
            ),
            actions=[NotificationsClearByIdAction(id=f'web_ui:pending:{action.id}')],
            events=[] if new_active_inputs else [WebUICheckHotspotEvent()],
        )

    return state
