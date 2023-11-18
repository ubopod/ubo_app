from ubo_gui.menu.types import Menu
from ubo_gui.notification import notification_manager

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
            'action': lambda: print('About'),
            'icon': 'info',
        },
    ],
}

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
                'title': lambda: f'Notifications ({notification_manager.unread_count})',
                'items': notification_manager.menu_items,
            },
            'color': 'yellow',
            'icon': 'info',
            'is_short': True,
        },
        {
            'label': 'Turn off',
            'action': lambda: print('Turning off'),
            'icon': 'power_settings_new',
            'is_short': True,
        },
    ],
}
