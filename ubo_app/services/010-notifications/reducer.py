# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from kivy.utils import get_color_from_hex
from redux import (
    BaseEvent,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.notifications import (
    Importance,
    NotificationDisplayType,
    NotificationsAction,
    NotificationsAddAction,
    NotificationsClearAction,
    NotificationsClearAllAction,
    NotificationsClearEvent,
    NotificationsDisplayEvent,
    NotificationsState,
)
from ubo_app.store.services.rgb_ring import RgbRingBlinkAction
from ubo_app.store.services.sound import SoundPlayChimeAction

Action = InitAction | NotificationsAction
ResultAction = RgbRingBlinkAction | SoundPlayChimeAction


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
        if action.notification.display_type in (
            NotificationDisplayType.FLASH,
            NotificationDisplayType.STICKY,
        ):
            events.append(NotificationsDisplayEvent(notification=action.notification))
        if action.notification in state.notifications:
            return CompleteReducerResult(state=state, events=events)
        kivy_color = get_color_from_hex(action.notification.color)
        return CompleteReducerResult(
            state=replace(
                state,
                notifications=[
                    *[
                        notification
                        for notification in state.notifications
                        if notification.id != action.notification.id
                    ],
                    action.notification,
                ],
                unread_count=state.unread_count + 1,
            ),
            actions=[
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
                SoundPlayChimeAction(name=action.notification.chime),
            ],
            events=events,
        )
    if isinstance(action, NotificationsClearAction):
        return CompleteReducerResult(
            state=replace(
                state,
                notifications=[
                    notification
                    for notification in state.notifications
                    if notification is not action.notification
                ],
                unread_count=state.unread_count - 1
                if action.notification in state.notifications
                else state.unread_count,
            ),
            events=[NotificationsClearEvent(notification=action.notification)],
        )
    if isinstance(action, NotificationsClearAllAction):
        return replace(state, notifications=[], unread_count=0)
    return state
