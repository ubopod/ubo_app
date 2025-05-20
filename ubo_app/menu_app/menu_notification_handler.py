# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import functools
import math
import weakref
from dataclasses import replace
from typing import TYPE_CHECKING

from kivy.clock import Clock, mainthread
from kivy.properties import StringProperty
from ubo_gui.app import UboApp
from ubo_gui.menu.stack_item import StackApplicationItem
from ubo_gui.notification import NotificationWidget
from ubo_gui.page import PAGE_MAX_ITEMS

from ubo_app.colors import DANGER_COLOR, INFO_COLOR
from ubo_app.logger import logger
from ubo_app.menu_app.notification_info import NotificationInfo
from ubo_app.store.core.types import CloseApplicationAction
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationApplicationItem,
    NotificationDisplayType,
    NotificationsClearAction,
    NotificationsClearEvent,
    NotificationsDisplayEvent,
)
from ubo_app.store.services.speech_synthesis import SpeechSynthesisReadTextAction
from ubo_app.utils.gui import UboPageWidget

if TYPE_CHECKING:
    from collections.abc import Callable

    from kivy._clock import ClockEvent
    from ubo_gui.menu.menu_widget import MenuWidget
    from ubo_gui.menu.types import Menu, PageWidget


class NotificationReference:
    def __init__(self, notification: Notification) -> None:
        self.value = notification
        self.dismiss_on_close = notification.dismiss_on_close
        self.is_initialized = False
        self.flash_event: ClockEvent | None = None


class UboNotificationWidget(NotificationWidget, UboPageWidget):
    """renders a notification."""

    notification_id: str = StringProperty()


class MenuNotificationHandler(UboApp):
    menu_widget: MenuWidget

    @mainthread
    def display_notification(  # noqa: C901
        self,
        event: NotificationsDisplayEvent,
    ) -> None:
        if (
            event.notification.id
            and any(
                isinstance(stack_item, StackApplicationItem)
                and isinstance(stack_item.application, UboNotificationWidget)
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

        logger.debug('Opening notification %s', notification.value.id)

        @mainthread
        def close(_: object = None) -> None:
            nonlocal is_closed
            logger.debug(
                'Closing notification %s',
                notification.value.id,
                extra={'is_closed': is_closed},
            )
            if is_closed:
                return
            is_closed = True
            for unsubscribe in subscriptions:
                unsubscribe()
            notification_application.unbind(on_close=close)
            store.dispatch(
                CloseApplicationAction(
                    application_instance_id=notification_application.id,
                ),
            )
            if notification.dismiss_on_close:
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
            logger.verbose('Renewing notification', extra={'notification': event})
            self = _self()
            if self is None:
                return
            if event.notification.id == notification.value.id:
                notification.value = event.notification
                notification.dismiss_on_close = event.notification.dismiss_on_close
                self._update_notification_widget(
                    notification_application,
                    event,
                    notification,
                    close,
                )

                if notification.flash_event:
                    notification.flash_event.cancel()
                    notification.flash_event = None

                if (
                    event.notification.display_type is NotificationDisplayType.FLASH
                    and event.index is None
                ):
                    notification.flash_event = Clock.schedule_once(
                        close,
                        notification.value.flash_time,
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
                    SpeechSynthesisReadTextAction(
                        information=event.notification.extra_information,
                    ),
                )

        notification_application = UboNotificationWidget(items=[None] * PAGE_MAX_ITEMS)
        notification_application.notification_id = notification.value.id

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

        self.menu_widget.open_application(notification_application)

    def _notification_items(  # noqa: C901
        self,
        notification: NotificationReference,
        close: Callable[[], None],
    ) -> list[NotificationActionItem | NotificationApplicationItem | None]:
        def dismiss(_: object = None) -> None:
            close()
            if not notification.dismiss_on_close:
                store.dispatch(
                    NotificationsClearAction(notification=notification.value),
                )

        def run_notification_action(
            action: NotificationActionItem,
        ) -> Menu | Callable[[], Menu] | type[PageWidget] | PageWidget | None:
            result = action.action()
            if action.close_notification:
                if action.dismiss_notification:
                    dismiss()
                else:
                    close()
            return result

        items: list[NotificationActionItem | NotificationApplicationItem | None] = []

        if notification.value.extra_information:
            text = notification.value.extra_information.text

            def open_info() -> PageWidget:
                return NotificationInfo(text=text)

            items.append(
                NotificationActionItem(
                    icon='󰋼',
                    action=open_info,
                    label='',
                    is_short=True,
                    background_color=INFO_COLOR,
                ),
            )

        def get_application_runner(
            action: NotificationApplicationItem,
        ) -> Callable[[], PageWidget | type[PageWidget]]:
            def run_application() -> PageWidget | type[PageWidget]:
                if callable(action.application) and not isinstance(
                    action.application,
                    type,
                ):
                    return action.application()
                return action.application

            return run_application

        items += [
            replace(
                action,
                is_short=True,
                action=(
                    action_ := functools.partial(run_notification_action, action),
                    setattr(action_, '_is_default_action_of_ubo_dispatch_item', True),
                )[0],
            )
            if isinstance(action, NotificationActionItem)
            else NotificationActionItem(
                action=get_application_runner(action),
                background_color=action.background_color,
                close_notification=action.close_notification,
                color=action.color,
                dismiss_notification=action.dismiss_notification,
                icon=action.icon,
                is_short=True,
                key=action.key,
                label=action.label,
                opacity=action.opacity,
                progress=action.progress,
            )
            for action in notification.value.actions
        ]

        if notification.value.show_dismiss_action:
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
        self,
        notification_application: UboNotificationWidget,
        event: NotificationsDisplayEvent,
        notification: NotificationReference,
        close: Callable[[], None],
    ) -> None:
        notification_application.notification_title = notification.value.title
        notification_application.content = notification.value.content
        notification_application.icon = notification.value.icon + (
            f'[size=20dp] {notification.value.progress:05.1%}[/size]'
            if notification.value.progress is not None
            and not math.isnan(notification.value.progress)
            else ''
        )
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
