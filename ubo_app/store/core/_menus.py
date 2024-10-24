from __future__ import annotations

import socket
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from redux import AutorunOptions
from ubo_gui.menu.types import (
    HeadedMenu,
    HeadlessMenu,
    SubMenuItem,
)

from ubo_app.store.core import (
    SETTINGS_ICONS,
    PowerOffAction,
    RebootAction,
    SettingsCategory,
)
from ubo_app.store.dispatch_action import DispatchItem
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Notification,
    NotificationsDisplayAction,
)
from ubo_app.store.update_manager.utils import (
    BASE_IMAGE,
    CURRENT_VERSION,
    about_menu_items,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item


APPS_MENU = HeadlessMenu(
    title='󰀻Docker Apps',
    items=[],
    placeholder='No apps',
)

SETTINGS_MENU = HeadlessMenu(
    title='Settings',
    items=[
        SubMenuItem(
            key=category,
            label=category,
            icon=SETTINGS_ICONS[category],
            sub_menu=HeadlessMenu(
                title=SETTINGS_ICONS[category] + category,
                items=[],
                placeholder='No settings in this category',
            ),
        )
        for category in SettingsCategory
    ],
)


MAIN_MENU = HeadlessMenu(
    title='󰍜Main',
    items=[
        SubMenuItem(
            key='home',
            label='Apps',
            icon='󰀻',
            sub_menu=APPS_MENU,
        ),
        SubMenuItem(
            key='settings',
            label='Settings',
            icon='',
            sub_menu=SETTINGS_MENU,
        ),
        SubMenuItem(
            key='about',
            label='About',
            icon='',
            sub_menu=HeadedMenu(
                title='About',
                heading=f'Ubo v{CURRENT_VERSION}',
                sub_heading=f'Base image: {BASE_IMAGE[:11]}\n{BASE_IMAGE[11:]}',
                items=about_menu_items,
            ),
        ),
    ],
)


@store.autorun(
    lambda state: state.notifications.unread_count,
    options=AutorunOptions(default_value='Notifications (not loaded)'),
)
def notifications_title(unread_count: int) -> str:
    return f'Notifications ({unread_count})'


@store.autorun(
    lambda state: state.notifications.notifications,
    options=AutorunOptions(default_value=[]),
)
def notifications_menu_items(notifications: Sequence[Notification]) -> list[Item]:
    """Return a list of menu items for the notification manager."""
    return [
        DispatchItem(
            key=str(notification.id),
            label=notification.title,
            icon=notification.icon,
            color='black',
            background_color=notification.color,
            store_action=NotificationsDisplayAction(
                notification=notification,
                index=index,
                count=len(notifications),
            ),
            progress=notification.progress,
        )
        for index, notification in enumerate(notifications)
        if notification.expiration_timestamp is None
        or notification.expiration_timestamp > datetime.now(tz=UTC)
    ]


@store.autorun(
    lambda state: len(state.notifications.notifications),
    options=AutorunOptions(default_value='white'),
)
def notifications_color(unread_count: int) -> str:
    return 'yellow' if unread_count > 0 else 'white'


HOME_MENU = HeadlessMenu(
    title=f'󰋜{socket.gethostname()}.local',
    items=[
        SubMenuItem(
            key='main',
            label='',
            sub_menu=MAIN_MENU,
            icon='󰍜',
            is_short=True,
        ),
        SubMenuItem(
            key='notifications',
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
        SubMenuItem(
            key='power',
            label='',
            sub_menu=HeadlessMenu(
                title='󰐥Power',
                items=[
                    DispatchItem(
                        label='Reboot',
                        store_action=RebootAction(),
                        icon='󰜉',
                    ),
                    DispatchItem(
                        label='Power off',
                        store_action=PowerOffAction(),
                        icon='󰐥',
                    ),
                ],
            ),
            icon='󰐥',
            is_short=True,
        ),
    ],
)
