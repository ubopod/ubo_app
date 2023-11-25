# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.stencilview import StencilView
from kivy.uix.widget import Widget
from ubo_gui.app import UboApp

from ubo_app.store import autorun

if TYPE_CHECKING:
    from ubo_app.store.status_icons import IconState


class MenuAppFooter(UboApp):
    @cached_property
    def clock_widget(self: MenuAppFooter) -> Label:
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
    def footer(self: MenuAppFooter) -> Widget:
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

        @autorun(lambda state: state.status_icons.icons)
        def render_icons(selector_result: list[IconState]) -> None:
            icons = selector_result
            icons_layout.clear_widgets()
            for icon in icons[:5]:
                label = Label(
                    text=icon.symbol,
                    color=icon.color,
                    font_name='material_symbols',
                    font_size=dp(20),
                    font_features='fill=1',
                    size_hint=(None, 1),
                    width=dp(24),
                )
                icons_layout.add_widget(label)
            icons_layout.bind(minimum_width=icons_layout.setter('width'))

        home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(16)))

        @autorun(lambda state: len(state.main.path))
        def handle_depth_change(selector_result: int) -> None:
            depth = selector_result
            is_deep = depth > 0
            if not is_deep:
                if normal_footer_layout in layout.children:
                    layout.remove_widget(normal_footer_layout)
                    layout.add_widget(home_footer_layout)
            elif home_footer_layout in layout.children:
                layout.remove_widget(home_footer_layout)
                layout.add_widget(normal_footer_layout)

        layout.add_widget(home_footer_layout)

        return layout
