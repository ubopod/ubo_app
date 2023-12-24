from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.logging import logger

if TYPE_CHECKING:
    from ubo_gui.menu.types import Item, Menu

SETTINGS_MENU: Menu = {
    'title': 'Settings',
    'items': [],
}

APPS_MENU: Menu = {
    'title': 'Apps',
    'items': [],
}

MAIN_MENU: Menu = {
    'title': 'Main',
    'items': [
        {
            'label': 'Apps',
            'icon': 'apps',
            'sub_menu': APPS_MENU,
        },
        {
            'label': 'Settings',
            'icon': 'settings',
            'sub_menu': SETTINGS_MENU,
        },
        {
            'label': 'About',
            'action': lambda: logger.info('"About" selected!'),
            'icon': 'info',
        },
    ],
}


def notifications_title() -> str:
    from ubo_gui.notification import notification_manager

    return f'Notifications ({notification_manager.unread_count})'


def notifications_menu_items() -> list[Item]:
    from ubo_gui.notification import notification_manager

    return notification_manager.menu_items()


HOME_MENU: Menu = {
    'title': 'Dashboard',
    'items': [
        {
            'label': '',
            'sub_menu': MAIN_MENU,
            'icon': 'menu',
            'is_short': True,
        },
        {
            'label': '',
            'sub_menu': {
                'title': notifications_title,
                'items': notifications_menu_items,
            },
            'color': 'yellow',
            'icon': 'info',
            'is_short': True,
        },
        {
            'label': 'Turn off',
            'action': lambda: logger.info('"Turn off" selected!'),
            'icon': 'power_settings_new',
            'is_short': True,
        },
    ],
}
