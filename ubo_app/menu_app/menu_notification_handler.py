# ruff: noqa: D100, D101, D102, D107
from __future__ import annotations

import functools
import math
import weakref
from typing import TYPE_CHECKING

from kivy.clock import Clock, mainthread
from kivy.metrics import dp
from kivy.properties import StringProperty
from ubo_gui.app import UboApp
from ubo_gui.menu.stack_item import StackApplicationItem
from ubo_gui.menu.types import ActionItem, HeadlessMenu
from ubo_gui.notification import NotificationWidget
from ubo_gui.page import PAGE_MAX_ITEMS

from ubo_app.colors import INFO_COLOR
from ubo_app.logger import logger
from ubo_app.menu_app.notification_info import NotificationInfo
from ubo_app.store.core.action_registry import get_action
from ubo_app.store.core.types import CloseApplicationAction
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationApplicationItem,
    NotificationDispatchItem,
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

    def go_up(self: UboNotificationWidget) -> None:
        """Scroll up the notification content."""
        self.ids.slider.animated_value += dp(100)

    def go_down(self: UboNotificationWidget) -> None:
        """Scroll down the notification content."""
        self.ids.slider.animated_value -= dp(100)


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
            if notification.value.on_close_id:
                from ubo_app.store.core.callback_registry import (
                    execute_callback,
                    unregister_callback,
                )

                execute_callback(notification.value.on_close_id)
                unregister_callback(notification.value.on_close_id)

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

        notification_application = UboNotificationWidget(
            notification_id=notification.value.id,
            items=[None] * PAGE_MAX_ITEMS,
        )

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
    ) -> list[ActionItem | None]:
        def dismiss(_: object = None) -> None:
            close()
            if not notification.dismiss_on_close:
                store.dispatch(
                    NotificationsClearAction(notification=notification.value),
                )

        def _make_action_callable(
            action: NotificationActionItem,
        ) -> Callable[
            [],
            Menu | Callable[[], Menu] | type[PageWidget] | PageWidget | None,
        ]:
            """Build a callable for a notification action item."""

            def run() -> (
                Menu | Callable[[], Menu] | type[PageWidget] | PageWidget | None
            ):
                result: Menu | Callable[[], Menu] | type[PageWidget] | PageWidget | None = None  # noqa: E501
                # Handle dispatch items
                if isinstance(action, NotificationDispatchItem) and action.store_action:
                    sa = action.store_action
                    if isinstance(sa, list):
                        store.dispatch(*sa)
                    else:
                        store.dispatch(sa)
                # Handle application items
                elif (
                    isinstance(action, NotificationApplicationItem)
                    and action.application_id
                ):
                    from ubo_app.store.ubo_actions import get_registered_application

                    app_cls = get_registered_application(action.application_id)
                    return app_cls
                # Handle action_id (registered callable)
                elif action.action_id:
                    handler = get_action(action.action_id)
                    if handler:
                        handler_result = handler()
                        if handler_result is not None:
                            result = handler_result  # type: ignore[assignment]

                if action.close_notification:
                    if action.dismiss_notification:
                        dismiss()
                    else:
                        close()
                return result

            return run

        def _to_action_item(action: NotificationActionItem) -> ActionItem:
            """Convert a serializable NotificationActionItem to ubo_gui ActionItem."""
            action_callable = _make_action_callable(action)
            setattr(  # noqa: B010
                action_callable,
                '_is_default_action_of_ubo_dispatch_item',
                True,
            )
            bg_color = (
                action.background_color
                if isinstance(action.background_color, str)
                else None
            )
            return ActionItem(
                key=action.key or None,
                label=action.label,
                icon=action.icon,
                color=action.color,
                is_short=True,
                background_color=bg_color,
                action=action_callable,
            )

        top_items: list[ActionItem | None] = []
        bottom_items: list[ActionItem | None] = []

        if notification.value.extra_information:
            text = notification.value.extra_information.text

            top_items.append(
                ActionItem(
                    key='info',
                    icon='󰋼',
                    action=lambda: NotificationInfo(text=text),
                    label='',
                    is_short=True,
                    background_color=INFO_COLOR,
                ),
            )

        if notification.value.show_dismiss_action:
            bottom_items.append(
                ActionItem(
                    key='dismiss',
                    icon='',
                    action=dismiss,
                    label='',
                    is_short=True,
                    background_color='#C0C0C0',
                ),
            )

        actions_quantity = (
            len(top_items) + len(notification.value.actions) + len(bottom_items)
        )

        if actions_quantity > PAGE_MAX_ITEMS:

            def open_options() -> HeadlessMenu:
                return HeadlessMenu(
                    title=notification.value.icon + ' Select',
                    items=[
                        _to_action_item(action)
                        for action in notification.value.actions
                    ],
                )

            return (
                top_items
                + [
                    _to_action_item(action)
                    for action in notification.value.actions[
                        : PAGE_MAX_ITEMS - len(top_items) - len(bottom_items) - 1
                    ]
                ]
                + [
                    ActionItem(
                        key='all',
                        icon='󰍜',
                        action=open_options,
                        is_short=True,
                    ),
                ]
                + bottom_items
            )

        items = (
            top_items
            + [_to_action_item(action) for action in notification.value.actions]
            + bottom_items
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
