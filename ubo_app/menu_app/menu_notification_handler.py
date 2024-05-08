# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import functools
import re
from dataclasses import replace

from kivy.clock import Clock, mainthread
from ubo_gui.app import UboApp
from ubo_gui.constants import DANGER_COLOR, INFO_COLOR
from ubo_gui.notification import NotificationWidget
from ubo_gui.page import PAGE_MAX_ITEMS

from ubo_app.menu_app.notification_info import NotificationInfo
from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.main import CloseApplicationEvent, OpenApplicationEvent
from ubo_app.store.services.notifications import (
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsClearAction,
    NotificationsClearEvent,
    NotificationsDisplayEvent,
)
from ubo_app.store.services.voice import VoiceReadTextAction


class MenuNotificationHandler(UboApp):
    @mainthread
    def display_notification(  # noqa: C901
        self: MenuNotificationHandler,
        event: NotificationsDisplayEvent,
    ) -> None:
        def run_notification_action(action: NotificationActionItem) -> None:
            if action.dismiss_notification:
                dismiss()
            return action.action()

        notification = event.notification

        @mainthread
        def dismiss(_: object = None) -> None:
            notification_application.unbind(on_close=dismiss)
            dispatch(
                CloseApplicationEvent(application=notification_application),
                NotificationsClearAction(notification=notification),
            )

        items = []

        if notification.extra_information:
            processed_voice_text = re.sub(
                r'\{[^{}|]*\|"(.?((?<!\|").(?!"\}))*.?)"\}',
                lambda match: match.groups()[0],
                notification.extra_information or '',
            )
            dispatch(VoiceReadTextAction(text=processed_voice_text))

            def open_info() -> None:
                previous_iteration = notification.extra_information or ''
                while True:
                    processed_visual_text = re.sub(
                        r'\{([^{}|]*)\|[^{}|]*\}',
                        lambda match: match.groups()[0],
                        previous_iteration,
                    ).replace('  ', '')
                    if processed_visual_text == previous_iteration:
                        break
                    previous_iteration = processed_visual_text
                info_application = NotificationInfo(text=processed_visual_text)

                dispatch(OpenApplicationEvent(application=info_application))

            items.append(
                NotificationActionItem(
                    icon='󰋼',
                    action=open_info,
                    label='',
                    is_short=True,
                    background_color=INFO_COLOR,
                ),
            )

        items += [
            replace(
                action,
                is_short=True,
                action=functools.partial(run_notification_action, action),
            )
            for action in notification.actions
        ]

        if notification.dismissable:
            items.append(
                NotificationActionItem(
                    icon='󰆴',
                    action=dismiss,
                    label='',
                    is_short=True,
                    background_color=DANGER_COLOR,
                ),
            )

        items = [None] * (PAGE_MAX_ITEMS - len(items)) + items

        notification_application = NotificationWidget(
            notification_title=notification.title,
            content=notification.content,
            icon=notification.icon,
            color=notification.color,
            items=items,
            title=f'Notification ({event.index+1}/{event.count})'
            if event.index is not None
            else ' ',
        )

        dispatch(OpenApplicationEvent(application=notification_application))

        if notification.display_type is NotificationDisplayType.FLASH:
            Clock.schedule_once(
                lambda _: dispatch(
                    CloseApplicationEvent(application=notification_application),
                ),
                notification.flash_time,
            )

        notification_application.bind(on_close=dismiss)

        @mainthread
        def clear_notification(event: NotificationsClearEvent) -> None:
            if event.notification == notification:
                dispatch(CloseApplicationEvent(application=notification_application))
                unsubscribe()
                if notification.on_close:
                    notification.on_close()

        unsubscribe = subscribe_event(
            NotificationsClearEvent,
            clear_notification,
        )
