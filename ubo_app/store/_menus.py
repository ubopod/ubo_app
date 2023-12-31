from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from kivy.clock import Clock
from ubo_gui.menu.types import ActionItem, ApplicationItem, HeadlessMenu, SubMenuItem
from ubo_gui.notification import NotificationWidget

from ubo_app.logging import logger
from ubo_app.store import autorun, dispatch
from ubo_app.store.notifications import NotificationsClearAction

if TYPE_CHECKING:
    from ubo_gui.menu.types import Item

    from ubo_app.store.notifications import Notification

SETTINGS_MENU = HeadlessMenu(
    title='Settings',
    items=[],
)

APPS_MENU = HeadlessMenu(
    title='Apps',
    items=[],
)

MAIN_MENU = HeadlessMenu(
    title='Main',
    items=[
        SubMenuItem(
            label='Apps',
            icon='apps',
            sub_menu=APPS_MENU,
        ),
        SubMenuItem(
            label='Settings',
            icon='settings',
            sub_menu=SETTINGS_MENU,
        ),
        ActionItem(
            label='About',
            action=lambda: logger.info('"About" selected!'),
            icon='info',
        ),
    ],
)


@autorun(lambda store: store.notifications.unread_count)
def notifications_title(unread_count: int) -> str:
    return f'Notifications ({unread_count})'


@autorun(lambda store: store.notifications.notifications)
def notifications_menu_items(notifications: Sequence[Notification]) -> list[Item]:
    """Return a list of menu items for the notification manager."""

    def notification_widget_builder(
        notification: Notification,
        index: int,
    ) -> type[NotificationWidget]:
        """Return a notification widget for the given notification."""

        class NotificationWrapper(NotificationWidget):
            def __init__(self: NotificationWrapper, **kwargs: object) -> None:
                super().__init__(
                    **kwargs,
                    title=f'Notification ({index+1}/{len(notifications)})',
                    notification_title=notification.title,
                    content=notification.content,
                    color=notification.color,
                    icon=notification.icon,
                )

            def on_dismiss(self: NotificationWrapper) -> None:
                dispatch(
                    NotificationsClearAction(notification=notification),
                )
                Clock.schedule_once(lambda _: self.dispatch('on_close'), -1)

        return NotificationWrapper

    return [
        ApplicationItem(
            label=notification.title,
            icon=notification.icon,
            color='black',
            background_color=notification.color,
            application=notification_widget_builder(notification, index),
        )
        for index, notification in enumerate(notifications)
    ]


HOME_MENU = HeadlessMenu(
    title='Dashboard',
    items=[
        SubMenuItem(
            label='',
            sub_menu=MAIN_MENU,
            icon='menu',
            is_short=True,
        ),
        SubMenuItem(
            label='',
            sub_menu=HeadlessMenu(
                title=notifications_title,
                items=notifications_menu_items,
            ),
            color='yellow',
            icon='info',
            is_short=True,
        ),
        ActionItem(
            label='Turn off',
            action=lambda: logger.info('"Turn off" selected!'),
            icon='power_settings_new',
            is_short=True,
        ),
    ],
)
