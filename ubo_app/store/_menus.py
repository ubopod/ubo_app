from ubo_gui.menu.types import Menu
from ubo_gui.notification import notification_manager

SETTINGS_MENU: Menu = {
    'title': 'Settings',
    'heading': 'Please choose',
    'sub_heading': 'This is sub heading',
    'items': lambda: [],
}

MAIN_MENU: Menu = {
    'title': 'Main',
    'heading': 'What are you going to do?',
    'sub_heading': 'Choose from the options',
    'items': [
        {
            'label': 'Settings',
            'icon': 'settings',
            'sub_menu': SETTINGS_MENU,
        },
        {
            'label': 'Apps',
            'action': lambda: print('Apps'),
            'icon': 'apps',
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
