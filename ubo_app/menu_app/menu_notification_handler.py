# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import functools
from dataclasses import replace
from typing import TYPE_CHECKING

from kivy.clock import Clock, mainthread
from ubo_gui.app import UboApp
from ubo_gui.constants import DANGER_COLOR, INFO_COLOR
from ubo_gui.menu.stack_item import StackApplicationItem
from ubo_gui.notification import NotificationWidget
from ubo_gui.page import PAGE_MAX_ITEMS

from ubo_app.menu_app.notification_info import NotificationInfo
from ubo_app.store.core import CloseApplicationEvent, OpenApplicationEvent
from ubo_app.store.main import dispatch, subscribe_event
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsClearAction,
    NotificationsClearEvent,
    NotificationsDisplayEvent,
)
from ubo_app.store.services.voice import VoiceReadTextAction

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_gui.menu.menu_widget import MenuWidget


class MenuNotificationHandler(UboApp):
    menu_widget: MenuWidget

    @mainthread
    def display_notification(  # noqa: C901
        self: MenuNotificationHandler,
        event: NotificationsDisplayEvent,
    ) -> None:
        if (
            event.notification.id
            and any(
                isinstance(stack_item, StackApplicationItem)
                and isinstance(stack_item.application, NotificationWidget)
                and stack_item.application.notification_id == event.notification.id
                for stack_item in self.menu_widget.stack
            )
        ) or event.notification.display_type is NotificationDisplayType.BACKGROUND:
            return

        subscriptions = []

        notification = event.notification
        is_closed = False

        @mainthread
        def close(_: object = None) -> None:
            nonlocal is_closed
            if is_closed:
                return
            is_closed = True
            for unsubscribe in subscriptions:
                unsubscribe()
            notification_application.unbind(on_close=close)
            dispatch(CloseApplicationEvent(application=notification_application))
            if notification.dismiss_on_close:
                dispatch(NotificationsClearAction(notification=notification))
            if notification.on_close:
                notification.on_close()

        notification_application = NotificationWidget(
            notification_title=notification.title,
            content=notification.content,
            icon=notification.icon,
            color=notification.color,
            items=self._notification_items(notification, close),
            title=f'Notification ({event.index + 1}/{event.count})'
            if event.index is not None
            else ' ',
        )
        notification_application.notification_id = notification.id

        dispatch(OpenApplicationEvent(application=notification_application))

        if notification.display_type is NotificationDisplayType.FLASH:
            Clock.schedule_once(close, notification.flash_time)

        notification_application.bind(on_close=close)

        @mainthread
        def clear_notification(event: NotificationsClearEvent) -> None:
            if event.notification == notification:
                close()

        def renew_notification(event: NotificationsDisplayEvent) -> None:
            nonlocal notification
            if event.notification.id == notification.id:
                notification = event.notification
                self._update_notification_widget(notification_application, event, close)

        subscriptions.append(
            subscribe_event(
                NotificationsClearEvent,
                clear_notification,
            ),
        )
        if notification.id is not None:
            subscriptions.append(
                subscribe_event(
                    NotificationsDisplayEvent,
                    renew_notification,
                    keep_ref=False,
                ),
            )

    def _notification_items(
        self: MenuNotificationHandler,
        notification: Notification,
        close: Callable[[], None],
    ) -> list[NotificationActionItem | None]:
        def dismiss(_: object = None) -> None:
            close()
            if not notification.dismiss_on_close:
                dispatch(NotificationsClearAction(notification=notification))

        def run_notification_action(action: NotificationActionItem) -> None:
            result = action.action()
            if action.dismiss_notification:
                dismiss()
            else:
                close()
            return result

        items: list[NotificationActionItem | None] = []

        if notification.extra_information:
            text = notification.extra_information.text
            dispatch(
                VoiceReadTextAction(
                    text=notification.extra_information.text,
                    piper_text=notification.extra_information.piper_text,
                    picovoice_text=notification.extra_information.picovoice_text,
                ),
            )

            def open_info() -> None:
                info_application = NotificationInfo(text=text)

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

        return [None] * (PAGE_MAX_ITEMS - len(items)) + items

    @mainthread
    def _update_notification_widget(
        self: MenuNotificationHandler,
        notification_application: NotificationWidget,
        event: NotificationsDisplayEvent,
        close: Callable[[], None],
    ) -> None:
        notification_application.notification_title = event.notification.title
        notification_application.content = event.notification.content
        notification_application.icon = event.notification.icon
        notification_application.color = event.notification.color
        notification_application.items = self._notification_items(
            event.notification,
            close,
        )
        notification_application.title = (
            f'Notification ({event.index + 1}/{event.count})'
            if event.index is not None
            else ' '
        )
