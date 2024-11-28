# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import datetime
import functools
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
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAction,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.store.services.web_ui import WebUIState

if TYPE_CHECKING:
    from redux import ReducerResult

DispatchAction = InputCancelAction | NotificationsAction


def reducer(
    state: WebUIState | None,
    action: InputAction,
) -> WebUIState | ReducerResult[WebUIState, DispatchAction, None]:
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
            actions=[
                NotificationsAddAction(
                    notification=Notification(
                        id='web_ui:pending',
                        icon='󱋆',
                        title='Web UI',
                        content=f'[size=18dp]{action.description.prompt}[/size]',
                        display_type=NotificationDisplayType.STICKY,
                        is_read=True,
                        extra_information=action.description.extra_information,
                        expiration_timestamp=datetime.datetime.now(tz=datetime.UTC),
                        color='#ffffff',
                        show_dismiss_action=False,
                        dismiss_on_close=True,
                        on_close=functools.partial(
                            store.dispatch,
                            InputCancelAction(id=action.description.id),
                        ),
                    ),
                ),
            ],
        )
    if isinstance(action, InputResolveAction | InputCancelAction):
        return CompleteReducerResult(
            state=replace(
                state,
                active_inputs=[
                    description
                    for description in state.active_inputs
                    if description.id != action.id
                ],
            ),
            actions=[NotificationsClearByIdAction(id='web_ui:pending')],
        )

    return state
