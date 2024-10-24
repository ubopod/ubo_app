# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from kivy.utils import get_color_from_hex
from redux import (
    BaseEvent,
    CompleteReducerResult,
    FinishAction,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.audio import AudioPlayChimeAction
from ubo_app.store.services.notifications import (
    Importance,
    NotificationsAction,
    NotificationsAddAction,
    NotificationsClearAction,
    NotificationsClearAllAction,
    NotificationsClearByIdAction,
    NotificationsClearEvent,
    NotificationsDisplayAction,
    NotificationsDisplayEvent,
    NotificationsState,
)
from ubo_app.store.services.rgb_ring import RgbRingBlinkAction

Action = InitAction | NotificationsAction
ResultAction = RgbRingBlinkAction | AudioPlayChimeAction


def reducer(
    state: NotificationsState | None,
    action: Action,
) -> ReducerResult[NotificationsState, ResultAction, BaseEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return NotificationsState(
                notifications=[],
                unread_count=0,
            )
        raise InitializationActionError(action)

    if isinstance(action, NotificationsAddAction):
        events = []
        events.append(NotificationsDisplayEvent(notification=action.notification))
        if action.notification in state.notifications:
            return CompleteReducerResult(state=state, events=events)
        kivy_color = get_color_from_hex(action.notification.color)
        new_notifications = (
            [
                action.notification
                if notification.id == action.notification.id
                else notification
                for notification in state.notifications
            ]
            if any(
                notification.id == action.notification.id
                for notification in state.notifications
            )
            else [action.notification, *state.notifications]
        )
        return CompleteReducerResult(
            state=replace(
                state,
                notifications=new_notifications,
                unread_count=sum(
                    1 for notification in new_notifications if not notification.is_read
                ),
                progress=sum(
                    notification.progress * notification.progress_weight
                    for notification in new_notifications
                    if notification.progress is not None
                )
                if any(
                    notification.progress is not None
                    for notification in new_notifications
                )
                else None,
            ),
            actions=[
                *(
                    [
                        RgbRingBlinkAction(
                            color=(
                                round(kivy_color[0] * 255),
                                round(kivy_color[1] * 255),
                                round(kivy_color[2] * 255),
                            ),
                            repetitions={
                                Importance.LOW: 1,
                                Importance.MEDIUM: 2,
                                Importance.HIGH: 3,
                                Importance.CRITICAL: 4,
                            }[action.notification.importance],
                            wait=400,
                        ),
                    ]
                    if action.notification.blink
                    else []
                ),
                *(
                    [AudioPlayChimeAction(name=action.notification.chime)]
                    if action.notification.chime
                    else []
                ),
            ],
            events=events,
        )
    if isinstance(action, NotificationsDisplayAction):
        return CompleteReducerResult(
            state=state,
            events=[
                NotificationsDisplayEvent(
                    notification=action.notification,
                    index=action.index,
                    count=action.count,
                ),
            ],
        )
    if isinstance(action, NotificationsClearAction):
        new_notifications = [
            notification
            for notification in state.notifications
            if notification is not action.notification
        ]
        return CompleteReducerResult(
            state=replace(
                state,
                notifications=new_notifications,
                unread_count=sum(
                    1 for notification in new_notifications if not notification.is_read
                ),
            ),
            events=[NotificationsClearEvent(notification=action.notification)],
        )
    if isinstance(action, NotificationsClearByIdAction):
        to_be_removed = [
            notification
            for notification in state.notifications
            if notification.id == action.id
        ]
        new_notifications = [
            notification
            for notification in state.notifications
            if notification.id != action.id
        ]
        return CompleteReducerResult(
            state=replace(
                state,
                notifications=new_notifications,
                unread_count=sum(
                    1 for notification in new_notifications if not notification.is_read
                ),
            ),
            events=[
                NotificationsClearEvent(notification=notification)
                for notification in to_be_removed
            ],
        )
    if isinstance(action, NotificationsClearAllAction | FinishAction):
        return CompleteReducerResult(
            state=replace(state, notifications=[], unread_count=0),
            events=[
                NotificationsClearEvent(notification=notification)
                for notification in state.notifications
            ],
        )
    return state
