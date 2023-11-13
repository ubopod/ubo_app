# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import datetime
import os
from functools import cached_property
from typing import TYPE_CHECKING, Any

from headless_kivy_pi import setup_headless
from kivy.app import Widget
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.stencilview import StencilView

from ubo_app.store import autorun

os.environ['KIVY_METRICS_DENSITY'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'

setup_headless()

from ubo_gui.app import UboApp  # noqa: E402
from ubo_gui.menu import MenuWidget  # noqa: E402
from ubo_gui.notification import SHORT_WIDTH, notification_manager  # noqa: E402
from ubo_gui.volume import VolumeWidget  # noqa: E402

if TYPE_CHECKING:
    from menu import Menu

    from ubo_app.store.status_icons import IconState


SETTINGS_MENU: Menu = {
    'title': 'Settings',
    'heading': 'Please choose',
    'sub_heading': 'This is sub heading',
    'items': [
        {
            'label': 'WiFi',
            'action': lambda: print('WiFi'),
            'icon': 'wifi',
        },
        {
            'label': 'Bluetooth',
            'action': lambda: print('Bluetooth'),
            'icon': 'bluetooth',
        },
        {
            'label': 'Audio',
            'action': lambda: print('Audio'),
            'icon': 'volume_up',
        },
    ],
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


class MenuApp(UboApp):
    """Menu application."""

    @cached_property
    def menu_widget(self: MenuApp) -> MenuWidget:
        """Build the main menu and initiate it."""
        menu_widget = MenuWidget()
        menu_widget.set_current_menu(HOME_MENU)

        def title_callback(_: MenuWidget, title: str) -> None:
            self.root.title = title

        self.root.title = menu_widget.title
        menu_widget.bind(title=title_callback)

        return menu_widget

    @cached_property
    def central(self: MenuApp) -> Widget:
        horizontal_layout = BoxLayout()

        self.menu_widget.size_hint = (None, 1)
        self.menu_widget.width = dp(SHORT_WIDTH)
        horizontal_layout.add_widget(self.menu_widget)

        central_column = BoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=dp(16),
        )
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

    @cached_property
    def clock_widget(self: MenuApp) -> Label:
        clock = Label(font_size=dp(20), size_hint=(None, 1))
        local_timzone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo

        def now() -> datetime.datetime:
            return datetime.datetime.now(local_timzone)

        def set_value(_: int) -> None:
            clock.text = now().strftime('%H:%M')

        set_value(0)

        def initialize(_: int) -> None:
            Clock.schedule_interval(set_value, 60)

        Clock.schedule_once(initialize, 60 - now().second + 1)

        return clock

    @cached_property
    def footer(self: MenuApp) -> Widget:
        layout = BoxLayout()

        normal_footer_layout = BoxLayout(orientation='horizontal', spacing=0, padding=0)
        normal_footer_layout.add_widget(
            Label(
                text='reply',
                font_name='material_symbols',
                font_size=dp(20),
                font_features='fill=1',
                size_hint=(None, 1),
            ),
        )
        normal_footer_layout.add_widget(Widget(size_hint=(1, 1)))

        home_footer_layout = BoxLayout(orientation='horizontal', spacing=0, padding=0)

        home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(16)))
        home_footer_layout.add_widget(self.clock_widget)
        home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(8)))

        icons_widget = StencilView(size_hint=(1, 1))
        home_footer_layout.add_widget(icons_widget)

        icons_layout = BoxLayout(
            orientation='horizontal',
            spacing=dp(4),
            padding=0,
        )
        icons_widget.add_widget(icons_layout)

        def set_icons_layout_x(*_: list[Any]) -> None:
            icons_layout.x = icons_widget.x + icons_widget.width - icons_layout.width

        icons_widget.bind(
            width=set_icons_layout_x,
            x=set_icons_layout_x,
            height=icons_layout.setter('height'),
            y=icons_layout.setter('y'),
        )
        icons_layout.bind(
            width=set_icons_layout_x,
            x=set_icons_layout_x,
        )

        @autorun(lambda state: state['status_icons']['icons'])
        def render_icons(icons: list[IconState]) -> None:
            icons_layout.clear_widgets()
            for icon in icons[:5]:
                label = Label(
                    text=icon['symbol'],
                    color=icon['color'],
                    font_name='material_symbols',
                    font_size=dp(20),
                    font_features='fill=1',
                    size_hint=(None, 1),
                    width=dp(24),
                )
                icons_layout.add_widget(label)
            icons_layout.bind(minimum_width=icons_layout.setter('width'))

        home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(16)))

        def handle_depth_change(_: Widget, depth: int) -> None:
            if depth == 0:
                if normal_footer_layout in layout.children:
                    layout.remove_widget(normal_footer_layout)
                    layout.add_widget(home_footer_layout)
            elif home_footer_layout in layout.children:
                layout.remove_widget(home_footer_layout)
                layout.add_widget(normal_footer_layout)

        self.menu_widget.bind(depth=handle_depth_change)

        layout.add_widget(home_footer_layout)

        return layout
