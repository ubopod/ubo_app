from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from redux import AutorunOptions
from ubo_gui.menu.types import (
    ActionItem,
    ApplicationItem,
    HeadedMenu,
    HeadlessMenu,
    SubMenuItem,
)
from ubo_gui.notification import NotificationWidget

from ubo_app.store import autorun, dispatch
from ubo_app.store.main import PowerOffAction, SettingsCategory
from ubo_app.store.services.notifications import Notification, NotificationsClearAction
from ubo_app.store.update_manager.utils import CURRENT_VERSION, about_menu_items

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item


APPS_MENU = HeadlessMenu(
    title='Apps',
    items=[],
    placeholder='No apps',
)

SETTINGS_MENU = HeadlessMenu(
    title='Settings',
    items=[
        SubMenuItem(
            label=category,
            sub_menu=HeadlessMenu(
                title=category,
                items=[],
                placeholder='No settings in this category',
            ),
        )
        for category in SettingsCategory
    ],
)


MAIN_MENU = HeadlessMenu(
    title='Main',
    items=[
        SubMenuItem(
            label='Apps',
            icon='󰀻',
            sub_menu=APPS_MENU,
        ),
        SubMenuItem(
            label='Settings',
            icon='',
            sub_menu=SETTINGS_MENU,
        ),
        SubMenuItem(
            label='About',
            icon='',
            sub_menu=HeadedMenu(
                title='About',
                heading=f'Ubo v{CURRENT_VERSION}',
                sub_heading='A universal dashboard for your Raspberry Pi',
                items=about_menu_items,
            ),
        ),
    ],
)


@autorun(
    lambda state: state.notifications.unread_count,
    options=AutorunOptions(default_value='Notifications (not loaded)'),
)
def notifications_title(unread_count: int) -> str:
    return f'Notifications ({unread_count})'


@autorun(
    lambda state: state.notifications.notifications,
    options=AutorunOptions(default_value=[]),
)
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
                self.dispatch('on_close')

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
        if notification.expiry_date is None
        or notification.expiry_date > datetime.now(tz=UTC)
    ]


@autorun(
    lambda state: len(state.notifications.notifications),
    options=AutorunOptions(default_value='white'),
)
def notifications_color(unread_count: int) -> str:
    return 'yellow' if unread_count > 0 else 'white'


HOME_MENU = HeadlessMenu(
    title='Dashboard',
    items=[
        SubMenuItem(
            label='',
            sub_menu=MAIN_MENU,
            icon='󰍜',
            is_short=True,
        ),
        SubMenuItem(
            label='',
            sub_menu=HeadlessMenu(
                title=notifications_title,
                items=notifications_menu_items,
                placeholder='No notifications',
            ),
            color=notifications_color,
            icon='',
            is_short=True,
        ),
        ActionItem(
            label='Turn off',
            action=lambda: dispatch(PowerOffAction()),
            icon='󰐥',
            is_short=True,
        ),
    ],
)
