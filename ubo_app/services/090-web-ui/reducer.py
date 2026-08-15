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
    WebUIAction,
    WebUIInitializeEvent,
    WebUIInputAction,
    WebUIInputEvent,
    WebUIState,
)

if TYPE_CHECKING:
    from redux import ReducerResult

DispatchAction = InputCancelAction | NotificationsAction


def reducer(
    state: WebUIState | None,
    action: InputAction | WebUIAction,
) -> ReducerResult[
    WebUIState,
    DispatchAction,
    WebUIInitializeEvent | WebUIInputEvent,
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
            # NOTE: resolving an input no longer tears down the hotspot. The
            # hotspot (owned by the wifi service) is stopped only by an explicit
            # WiFiStopHotspotAction when the Wi-Fi journey is complete, so
            # multi-step web flows keep it up across steps without dropping the
            # user's connection.
            new_active_inputs = [
                description
                for description in state.active_inputs
                if description.id != id
            ]
            return CompleteReducerResult(
                state=replace(
                    state,
                    active_inputs=new_active_inputs,
                ),
                actions=[NotificationsClearByIdAction(id=f'web_ui:pending:{id}')],
            )

        case WebUIInputAction(command=command):
            return CompleteReducerResult(
                state=state,
                events=[WebUIInputEvent(command=command)],
            )

        case _:
            return state
