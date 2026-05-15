# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import (
    BaseEvent,
    CompleteReducerResult,
    FinishAction,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.core.types import (
    StackPopNotificationAction,
    StackPushNotificationAction,
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
from ubo_app.utils.color import hex_to_rgb

Action = InitAction | NotificationsAction
# Stack push/pop is returned here — from the reducer, on the *ordered*
# action queue — rather than from a NotificationsDisplayEvent handler.
# Event handlers run in concurrent worker threads, so the dispatches
# would otherwise land out of order.
#
# ``NotificationsAddAction`` *always* pushes (idempotently): a
# notification's ``NotificationStackItem`` stays on the stack for its
# whole lifecycle, and the view computation decides whether to render it
# from ``display_type`` (BACKGROUND overlays are filtered out, STICKY /
# FLASH own the screen). That keeps the stack stable across the
# STICKY → BACKGROUND → FLASH lifecycle — no push/pop churn. The pop only
# happens when the notification is actually cleared/dismissed.
ResultAction = (
    RgbRingBlinkAction
    | AudioPlayChimeAction
    | StackPushNotificationAction
    | StackPopNotificationAction
)


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

    match action:
        case NotificationsAddAction():
            events = []
            events.append(NotificationsDisplayEvent(notification=action.notification))
            stack_action = StackPushNotificationAction(
                notification_id=action.notification.id,
            )
            if action.notification in state.notifications:
                return CompleteReducerResult(
                    state=state,
                    actions=[stack_action],
                    events=events,
                )
            rgb_color = hex_to_rgb(action.notification.color)
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
                        1
                        for notification in new_notifications
                        if not notification.is_read
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
                    stack_action,
                    *(
                        [
                            RgbRingBlinkAction(
                                color=rgb_color,
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

        case NotificationsDisplayAction():
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

        case NotificationsClearAction():
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
                        1
                        for notification in new_notifications
                        if not notification.is_read
                    ),
                ),
                actions=[
                    StackPopNotificationAction(
                        notification_id=action.notification.id,
                    ),
                ],
                events=[NotificationsClearEvent(notification=action.notification)],
            )

        case NotificationsClearByIdAction():
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
                        1
                        for notification in new_notifications
                        if not notification.is_read
                    ),
                ),
                actions=[StackPopNotificationAction(notification_id=action.id)],
                events=[
                    NotificationsClearEvent(notification=notification)
                    for notification in to_be_removed
                ],
            )

        case NotificationsClearAllAction() | FinishAction():
            return CompleteReducerResult(
                state=replace(state, notifications=[], unread_count=0),
                actions=[
                    StackPopNotificationAction(notification_id=notification.id)
                    for notification in state.notifications
                ],
                events=[
                    NotificationsClearEvent(notification=notification)
                    for notification in state.notifications
                ],
            )

        case _:
            return state
