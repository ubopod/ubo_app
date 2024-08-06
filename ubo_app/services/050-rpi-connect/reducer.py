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
from ubo_app.store.services.rpi_connect import (
    RPiConnectAction,
    RPiConnectDoneDownloadingAction,
    RPiConnectLoginEvent,
    RPiConnectSetPendingAction,
    RPiConnectSetStatusAction,
    RPiConnectStartDownloadingAction,
    RPiConnectState,
    RPiConnectUpdateServiceStateAction,
)


def reducer(
    state: RPiConnectState | None,
    action: RPiConnectAction,
) -> (
    CompleteReducerResult[RPiConnectState, NotificationsAddAction, BaseEvent]
    | RPiConnectState
):
    if state is None:
        if isinstance(action, InitAction):
            return RPiConnectState()
        raise InitializationActionError(action)

    if isinstance(action, RPiConnectStartDownloadingAction):
        return replace(state, is_downloading=True)

    if isinstance(action, RPiConnectDoneDownloadingAction):
        return replace(state, is_downloading=False)

    if isinstance(action, RPiConnectSetPendingAction):
        return replace(state, is_installed=None, is_signed_in=None, status=None)

    if isinstance(action, RPiConnectUpdateServiceStateAction):
        if action.is_active is not None:
            state = replace(state, is_active=action.is_active)
        return state

    if isinstance(action, RPiConnectSetStatusAction):
        actions = []
        events = []
        if state.is_signed_in is False and action.is_signed_in:
            actions.append(
                NotificationsAddAction(
                    notification=Notification(
                        title='RPi-Connect',
                        content='Successful Login',
                        icon='',
                        importance=Importance.MEDIUM,
                        color=SUCCESS_COLOR,
                        display_type=NotificationDisplayType.FLASH,
                    ),
                ),
            )
            events.append(RPiConnectLoginEvent())

        state = replace(
            state,
            is_installed=action.is_installed,
            is_signed_in=action.is_signed_in,
            status=action.status,
        )

        return CompleteReducerResult(state=state, actions=actions, events=events)

    return state
