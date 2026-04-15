# ruff: noqa: D100, D101, D102, D107
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from kivy.clock import mainthread
from kivy.metrics import dp
from kivy.properties import StringProperty
from ubo_gui.app import UboApp
from ubo_gui.menu.stack_item import StackApplicationItem
from ubo_gui.menu.types import HeadlessMenu
from ubo_gui.notification import NotificationWidget
from ubo_gui.page import PAGE_MAX_ITEMS

from ubo_gui_client.constants import INFO_COLOR
from ubo_gui_client.gui_utils import UboPageWidget
from ubo_gui_client.widgets.notification_info import NotificationInfo

if TYPE_CHECKING:
    from collections.abc import Callable

    from kivy._clock import ClockEvent
    from ubo_gui.menu.menu_widget import MenuWidget
    from ubo_gui.menu.types import ActionItem

    from ubo_gui_client.client import GUIClient

logger = logging.getLogger(__name__)


class NotificationReference:
    def __init__(self, notification: object) -> None:
        self.value = notification
        self.dismiss_on_close = getattr(notification, 'dismiss_on_close', False)
        self.is_initialized = False
        self.flash_event: ClockEvent | None = None


class UboNotificationWidget(NotificationWidget, UboPageWidget):
    """Renders a notification."""

    notification_id: str = StringProperty()

    def go_up(self: UboNotificationWidget) -> None:
        """Scroll up the notification content."""
        self.ids.slider.animated_value += dp(100)

    def go_down(self: UboNotificationWidget) -> None:
        """Scroll down the notification content."""
        self.ids.slider.animated_value -= dp(100)

    def scroll_to_page(
        self: UboNotificationWidget,
        page_index: int,
        total_pages: int,
    ) -> None:
        """Set text scroll position proportionally based on current page.

        Page 0 → slider at max (top of text).
        Last page → slider at 0 (bottom of text / end of content).
        """
        slider = self.ids.slider
        if total_pages <= 1 or slider.max <= 0:
            return
        fraction = page_index / (total_pages - 1)
        slider.animated_value = slider.max * (1 - fraction)


class MenuNotificationHandler(UboApp):
    menu_widget: MenuWidget
    grpc_client: GUIClient

    @mainthread
    def display_notification(
        self,
        event: object,
    ) -> None:
        notification_data = getattr(event, 'notification', None)
        if notification_data is None:
            return

        notification_id = getattr(notification_data, 'id', None)
        event_index = getattr(event, 'index', None)
        display_type = getattr(notification_data, 'display_type', None)

        if (
            notification_id
            and any(
                isinstance(stack_item, StackApplicationItem)
                and isinstance(stack_item.application, UboNotificationWidget)
                and stack_item.application.notification_id == notification_id
                for stack_item in self.menu_widget.stack
            )
        ) or (
            display_type is not None
            and str(display_type) == 'BACKGROUND'
            and event_index is None
        ):
            return

        subscriptions: list[Callable[[], None]] = []

        notification = NotificationReference(notification_data)
        is_closed = False

        logger.debug('Opening notification %s', notification_id)

        @mainthread
        def close(_: object = None) -> None:
            nonlocal is_closed
            logger.debug(
                'Closing notification %s',
                notification_id,
                extra={'is_closed': is_closed},
            )
            if is_closed:
                return
            is_closed = True
            for unsubscribe in subscriptions:
                unsubscribe()
            notification_application.unbind(on_close=close)
            self.grpc_client.dispatch_close_application(
                notification_application.id,
            )
            if notification.dismiss_on_close and notification_id:
                self.grpc_client.dispatch_notifications_clear(notification_id)
            on_close_id = getattr(notification.value, 'on_close_id', None)
            if on_close_id:
                try:
                    from ubo_app.store.core.callback_registry import (  # pyright: ignore[reportMissingImports]
                        execute_callback,
                        unregister_callback,
                    )

                    execute_callback(on_close_id)
                    unregister_callback(on_close_id)
                except ImportError:
                    logger.debug(
                        'callback_registry not available in GUI client',
                    )

        notification_application = UboNotificationWidget(
            notification_id=notification_id or '',
            items=[None] * PAGE_MAX_ITEMS,
        )

        notification_application.bind(on_close=close)
        self._update_notification_widget(
            notification_application,
            event,
            notification,
            close,
        )

        self.menu_widget.open_application(notification_application)

    def _notification_items(
        self,
        notification: NotificationReference,
        close: Callable[[], None],
    ) -> list[ActionItem | None]:
        def dismiss(_: object = None) -> None:
            close()
            notification_id = getattr(notification.value, 'id', None)
            if not notification.dismiss_on_close and notification_id:
                self.grpc_client.dispatch_notifications_clear(notification_id)

        from ubo_gui.menu.types import ActionItem

        top_items: list[ActionItem | None] = []
        bottom_items: list[ActionItem | None] = []

        extra_info = getattr(notification.value, 'extra_information', None)
        if extra_info:
            text = getattr(extra_info, 'text', str(extra_info))
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

        show_dismiss = getattr(notification.value, 'show_dismiss_action', True)
        if show_dismiss:
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

        actions = getattr(notification.value, 'actions', [])
        actions_quantity = len(top_items) + len(actions) + len(bottom_items)

        def _noop() -> None:
            pass

        def convert_action(action: object) -> ActionItem:
            action_fn = getattr(action, 'action', None) or _noop
            return ActionItem(
                key=getattr(action, 'key', ''),
                icon=getattr(action, 'icon', ''),
                label=getattr(action, 'label', ''),
                action=action_fn,
                is_short=True,
                background_color=getattr(action, 'background_color', ''),
                color=getattr(action, 'color', ''),
                opacity=getattr(action, 'opacity', 1.0),
                progress=getattr(action, 'progress', None),
            )

        if actions_quantity > PAGE_MAX_ITEMS:
            icon = getattr(notification.value, 'icon', '')

            def open_options() -> HeadlessMenu:
                return HeadlessMenu(
                    title=icon + ' Select',
                    items=[convert_action(action) for action in actions],
                )

            return (
                top_items
                + [
                    convert_action(action)
                    for action in actions[
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
            + [convert_action(action) for action in actions]
            + bottom_items
        )
        return [None] * (PAGE_MAX_ITEMS - len(items)) + items

    @mainthread
    def _update_notification_widget(
        self,
        notification_application: UboNotificationWidget,
        event: object,
        notification: NotificationReference,
        close: Callable[[], None],
    ) -> None:
        notification_application.notification_title = getattr(
            notification.value, 'title', '',
        )
        notification_application.content = getattr(notification.value, 'content', '')

        progress = getattr(notification.value, 'progress', None)
        icon = getattr(notification.value, 'icon', '')
        notification_application.icon = icon + (
            f'[size=20dp] {progress:05.1%}[/size]'
            if progress is not None and not math.isnan(progress)
            else ''
        )
        notification_application.color = getattr(notification.value, 'color', '')
        notification_application.items = self._notification_items(  # type: ignore[assignment]
            notification,
            close,
        )

        event_index = getattr(event, 'index', None)
        event_count = getattr(event, 'count', 0)
        notification_application.title = (
            f'Notification ({event_index + 1}/{event_count})'
            if event_index is not None
            else ' '
        )
