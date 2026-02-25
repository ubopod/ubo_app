# ruff: noqa: D100, D101, D102
from __future__ import annotations

import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any

from kivy.clock import Clock, mainthread
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.stencilview import StencilView
from kivy.uix.widget import Widget
from ubo_gui.app import UboApp

if TYPE_CHECKING:
    from collections.abc import Sequence


class MenuAppFooter(UboApp):
    @mainthread
    def set_temperature_value(self: MenuAppFooter, value: float | None = None) -> None:
        if value is None:
            self.temperature.text = ''
        else:
            self.temperature.text = f'{value:0.1f}󰔄'

    @cached_property
    def temperature_widget(self: MenuAppFooter) -> BoxLayout:
        layout = BoxLayout(
            orientation='horizontal',
            spacing=0,
            padding=0,
            width=dp(12),
            size_hint=(None, 1),
        )

        self.temperature = Label(font_size=dp(14), size_hint=(None, 1), valign='middle')
        self.temperature.bind(
            texture_size=lambda temperature, texture_size: setattr(
                temperature,
                'width',
                texture_size[0],
            )
            or setattr(layout, 'width', temperature.width + dp(12)),
        )

        icon = Label(
            text='\uf2c9',
            color='#ffffff',
            font_size=dp(16),
            size_hint=(None, 1),
            width=dp(12),
        )
        layout.add_widget(icon)
        layout.add_widget(self.temperature)

        return layout

    @mainthread
    def set_light_value(self: MenuAppFooter, value: float | None = None) -> None:
        if value is None:
            self.light.color = (1, 1, 1, 1)
        else:
            v = min(value, 140) / 140
            self.light.color = (1, 1, 1, v)

    @cached_property
    def light_widget(self: MenuAppFooter) -> Label:
        self.light = Label(
            text='󱩎',
            color='#ffffff',
            font_size=dp(16),
            font_features='fill=0',
            size_hint=(None, 1),
            width=dp(16),
        )
        self.light.bind(
            texture_size=lambda light, texture_size: setattr(
                light,
                'width',
                texture_size[0],
            ),
        )

        return self.light

    @cached_property
    def clock_widget(self: MenuAppFooter) -> Label:
        local_timzone = datetime.datetime.now(datetime.UTC).astimezone().tzinfo

        def now() -> datetime.datetime:
            return datetime.datetime.now(local_timzone)

        initial_time = now().strftime('%H:%M')
        clock = Label(
            text=initial_time,
            font_size=dp(20),
            size_hint=(None, 1),
            valign='middle',
        )
        clock.bind(
            texture_size=lambda clock, texture_size: setattr(
                clock,
                'width',
                texture_size[0],
            ),
        )

        def update(_: float | None = None) -> None:
            clock.text = now().strftime('%H:%M')
            now_ = now()
            Clock.schedule_once(
                update,
                60 - now_.second - now_.microsecond / 1_000_000 + 0.05,
            )

        Clock.schedule_once(update, 0)

        return clock

    @mainthread
    def render_icons(
        self: MenuAppFooter,
        icons: Sequence[object],
    ) -> None:
        self.icons_layout.clear_widgets()
        for icon in list(reversed(icons))[:4]:
            label = Label(
                text=getattr(icon, 'symbol', ''),
                color=getattr(icon, 'color', '#ffffff'),
                font_size=dp(20),
                font_features='fill=0',
                size_hint=(None, 1),
                width=dp(22),
                markup=True,
            )
            self.icons_layout.add_widget(label)
        self.icons_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))
        self.icons_layout.bind(minimum_width=self.icons_layout.setter('width'))
    @mainthread
    def handle_is_footer_visible_change(
        self: MenuAppFooter,
        is_footer_visible: bool,  # noqa: FBT001
    ) -> None:
        if is_footer_visible:
            if self.home_footer_layout not in self.footer_layout.children:
                self.footer_layout.add_widget(self.home_footer_layout)
        elif self.home_footer_layout in self.footer_layout.children:
            self.footer_layout.remove_widget(self.home_footer_layout)

    def set_icons_layout_x(self: MenuAppFooter, *_: list[Any]) -> None:
        self.icons_layout.x = (
            self.icons_widget.x + self.icons_widget.width - self.icons_layout.width
        )

    @cached_property
    def footer(self: MenuAppFooter) -> Widget | None:
        self.home_footer_layout = BoxLayout(
            orientation='horizontal',
            spacing=0,
            padding=0,
        )

        self.home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))
        self.home_footer_layout.add_widget(self.clock_widget)
        self.home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))
        self.home_footer_layout.add_widget(self.temperature_widget)
        self.home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))
        self.home_footer_layout.add_widget(self.light_widget)
        self.home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))

        self.icons_widget = StencilView(size_hint=(1, 1))
        self.home_footer_layout.add_widget(self.icons_widget)

        self.icons_layout = BoxLayout(
            orientation='horizontal',
            spacing=dp(4),
            padding=0,
        )
        self.icons_widget.add_widget(self.icons_layout)

        self.icons_widget.bind(
            width=self.set_icons_layout_x,
            x=self.set_icons_layout_x,
            height=self.icons_layout.setter('height'),
            y=self.icons_layout.setter('y'),
        )
        self.icons_layout.bind(
            width=self.set_icons_layout_x,
            x=self.set_icons_layout_x,
        )

        self.footer_layout = BoxLayout()
        self.footer_layout.add_widget(self.home_footer_layout)

        # Footer visibility is controlled by ViewRenderer via gRPC data

        return self.footer_layout
