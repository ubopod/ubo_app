# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import functools
import weakref
from dataclasses import replace
from typing import TYPE_CHECKING

from kivy.clock import Clock, mainthread
from ubo_gui.app import UboApp
from ubo_gui.constants import DANGER_COLOR, INFO_COLOR
from ubo_gui.menu.stack_item import StackApplicationItem
from ubo_gui.notification import NotificationWidget
from ubo_gui.page import PAGE_MAX_ITEMS

from ubo_app.menu_app.notification_info import NotificationInfo
from ubo_app.store.core import CloseApplicationAction, OpenApplicationAction
from ubo_app.store.main import store
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


class NotificationReference:
    def __init__(self: NotificationReference, notification: Notification) -> None:
        self.value = notification
        self.is_initialized = False


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
        ) or (
            event.notification.display_type is NotificationDisplayType.BACKGROUND
            and event.index is None
        ):
            return

        subscriptions = []

        notification = NotificationReference(event.notification)
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
            store.dispatch(CloseApplicationAction(application=notification_application))
            if notification.value.dismiss_on_close:
                store.dispatch(
                    NotificationsClearAction(notification=notification.value),
                )
            if notification.value.on_close:
                notification.value.on_close()

        def clear_notification(event: NotificationsClearEvent) -> None:
            if event.notification == notification.value:
                close()

        _self = weakref.ref(self)

        def renew_notification(event: NotificationsDisplayEvent) -> None:
            self = _self()
            if self is None:
                return
            if event.notification.id == notification.value.id:
                notification.value = event.notification
                self._update_notification_widget(
                    notification_application,
                    event,
                    notification,
                    close,
                )

            if event.notification.extra_information and (
                not notification.is_initialized
                or event.notification.id is None
                or event.notification.id != notification.value.id
                or not notification.value.extra_information
                or event.notification.extra_information
                != notification.value.extra_information
            ):
                notification.is_initialized = True
                store.dispatch(
                    VoiceReadTextAction(
                        text=event.notification.extra_information.text,
                        piper_text=event.notification.extra_information.piper_text,
                        picovoice_text=event.notification.extra_information.picovoice_text,
                    ),
                )

        notification_application = NotificationWidget(items=[None] * PAGE_MAX_ITEMS)
        notification_application.notification_id = notification.value.id

        if (
            notification.value.display_type is NotificationDisplayType.FLASH
            and event.index is None
        ):
            Clock.schedule_once(close, notification.value.flash_time)

        notification_application.bind(on_close=close)

        subscriptions.append(
            store.subscribe_event(
                NotificationsClearEvent,
                clear_notification,
            ),
        )
        if notification.value.id is not None:
            subscriptions.append(
                store.subscribe_event(
                    NotificationsDisplayEvent,
                    renew_notification,
                ),
            )

        renew_notification(event)

        store.dispatch(OpenApplicationAction(application=notification_application))

    def _notification_items(
        self: MenuNotificationHandler,
        notification: NotificationReference,
        close: Callable[[], None],
    ) -> list[NotificationActionItem | None]:
        def dismiss(_: object = None) -> None:
            close()
            if not notification.value.dismiss_on_close:
                store.dispatch(
                    NotificationsClearAction(notification=notification.value),
                )

        def run_notification_action(action: NotificationActionItem) -> None:
            result = action.action()
            if action.dismiss_notification:
                dismiss()
            else:
                close()
            return result

        items: list[NotificationActionItem | None] = []

        if notification.value.extra_information:
            text = notification.value.extra_information.text

            def open_info() -> None:
                info_application = NotificationInfo(text=text)

                store.dispatch(OpenApplicationAction(application=info_application))

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
            for action in notification.value.actions
        ]

        if notification.value.dismissable:
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
        notification: NotificationReference,
        close: Callable[[], None],
    ) -> None:
        notification_application.notification_title = notification.value.title
        notification_application.content = notification.value.content
        notification_application.icon = notification.value.icon
        notification_application.color = notification.value.color
        notification_application.items = self._notification_items(
            notification,
            close,
        )
        notification_application.title = (
            f'Notification ({event.index + 1}/{event.count})'
            if event.index is not None
            else ' '
        )
