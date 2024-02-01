from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Sequence

from kivy.clock import Clock
from redux import AutorunOptions, FinishAction
from ubo_gui.menu.types import (
    ActionItem,
    ApplicationItem,
    HeadedMenu,
    HeadlessMenu,
    SubMenuItem,
)
from ubo_gui.notification import NotificationWidget

from ubo_app.store import autorun, dispatch
from ubo_app.store.main import PowerOffAction
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationsClearAction,
)
from ubo_app.store.services.sound import SoundPlayChimeAction
from ubo_app.store.update_manager.utils import CURRENT_VERSION, about_menu_items

if TYPE_CHECKING:
    from ubo_gui.menu.types import Item


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
        SubMenuItem(
            label='About',
            icon='info',
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
        or notification.expiry_date > datetime.now(tz=timezone.utc)
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
            action=lambda: dispatch(
                SoundPlayChimeAction(name=Chime.FAILURE),
                PowerOffAction(),
                FinishAction(),
            ),
            icon='power_settings_new',
            is_short=True,
        ),
    ],
)
