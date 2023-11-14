# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from functools import cached_property
from threading import Thread
from typing import TYPE_CHECKING

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from ubo_gui.app import UboApp
from ubo_gui.gauge import GaugeWidget
from ubo_gui.menu import MenuWidget
from ubo_gui.menu.constants import SHORT_WIDTH
from ubo_gui.notification import notification_manager
from ubo_gui.volume import VolumeWidget

if TYPE_CHECKING:
    from kivy.uix.widget import Widget
    from ubo_gui.menu.types import Menu


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


class MenuAppCentral(UboApp):
    @cached_property
    def menu_widget(self: MenuAppCentral) -> MenuWidget:
        """Build the main menu and initiate it."""
        menu_widget = MenuWidget()
        menu_widget.set_current_menu(HOME_MENU)

        def title_callback(_: MenuWidget, title: str) -> None:
            self.root.title = title

        self.root.title = menu_widget.title
        menu_widget.bind(title=title_callback)

        return menu_widget

    @cached_property
    def cpu_gauge(self: MenuAppCentral) -> GaugeWidget:
        import psutil

        gauge = GaugeWidget(value=0, fill_color='#24D636', label='CPU')

        value = [0]

        def set_value(_: float) -> None:
            gauge.value = value[0]

        def calculate_value() -> None:
            value[0] = psutil.cpu_percent(interval=1, percpu=False)
            Clock.schedule_once(set_value)

        Clock.schedule_interval(
            lambda _: Thread(target=calculate_value).start(),
            1,
        )

        return gauge

    @cached_property
    def ram_gauge(self: MenuAppCentral) -> GaugeWidget:
        import psutil

        gauge = GaugeWidget(
            value=psutil.virtual_memory().percent,
            fill_color='#D68F24',
            label='RAM',
        )

        def set_value(_: int) -> None:
            gauge.value = psutil.virtual_memory().percent

        Clock.schedule_interval(set_value, 1)

        return gauge

    @cached_property
    def central(self: MenuAppCentral) -> Widget:
        horizontal_layout = BoxLayout()

        self.menu_widget.size_hint = (None, 1)
        self.menu_widget.width = dp(SHORT_WIDTH)
        horizontal_layout.add_widget(self.menu_widget)

        central_column = BoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=dp(16),
        )
        central_column.add_widget(self.cpu_gauge)
        central_column.add_widget(self.ram_gauge)
        central_column.size_hint = (1, 1)
        horizontal_layout.add_widget(central_column)

        right_column = BoxLayout(orientation='vertical')
        right_column.add_widget(VolumeWidget(value=40))
        right_column.size_hint = (None, 1)
        right_column.width = dp(SHORT_WIDTH)
        horizontal_layout.add_widget(right_column)

        def handle_depth_change(_: Widget, depth: int) -> None:
            if depth == 0:
                self.menu_widget.size_hint = (None, 1)
                self.menu_widget.width = dp(SHORT_WIDTH)
                central_column.size_hint = (1, 1)
                right_column.size_hint = (None, 1)
            else:
                self.menu_widget.size_hint = (1, 1)
                central_column.size_hint = (0, 1)
                right_column.size_hint = (0, 1)

        self.menu_widget.bind(depth=handle_depth_change)

        return horizontal_layout
