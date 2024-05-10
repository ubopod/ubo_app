# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    BaseEvent,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
)
from ubo_gui.constants import SUCCESS_COLOR

from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.vscode import (
    VSCodeAction,
    VSCodeDoneDownloadingAction,
    VSCodeSetPendingAction,
    VSCodeSetStatusAction,
    VSCodeStartDownloadingAction,
    VSCodeState,
)


def reducer(
    state: VSCodeState | None,
    action: VSCodeAction,
) -> (
    CompleteReducerResult[VSCodeState, NotificationsAddAction, BaseEvent] | VSCodeState
):
    if state is None:
        if isinstance(action, InitAction):
            return VSCodeState()
        raise InitializationActionError(action)

    if isinstance(action, VSCodeStartDownloadingAction):
        return replace(state, is_downloading=True)

    if isinstance(action, VSCodeDoneDownloadingAction):
        return replace(state, is_downloading=False)

    if isinstance(action, VSCodeSetPendingAction):
        return replace(state, is_pending=True)

    if isinstance(action, VSCodeSetStatusAction):
        actions = []
        if (
            state.status
            and not state.status.is_running
            and action.status
            and action.status.is_running
        ):
            actions.append(
                NotificationsAddAction(
                    notification=Notification(
                        title='VSCode',
                        content='Service is running',
                        icon='󰨞',
                        importance=Importance.MEDIUM,
                        color=SUCCESS_COLOR,
                        display_type=NotificationDisplayType.FLASH,
                    ),
                ),
            )

        state = replace(
            state,
            is_pending=False,
            is_binary_installed=action.is_binary_installed,
            is_logged_in=action.is_logged_in,
            status=action.status,
        )

        return CompleteReducerResult(state=state, actions=actions)

    return state
