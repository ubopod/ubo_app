# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any, Sequence

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
    def temperature_widget(self: MenuAppFooter) -> BoxLayout:
        layout = BoxLayout(
            orientation='horizontal',
            spacing=0,
            padding=0,
            size_hint=(None, 1),
        )

        temperature = Label(font_size=dp(14), size_hint=(None, 1), valign='middle')
        temperature.bind(
            texture_size=lambda temperature, texture_size: setattr(
                temperature,
                'width',
                texture_size[0],
            )
            or setattr(layout, 'width', temperature.width + dp(12)),
        )

        @autorun(lambda state: state.sensors.temperature.value)
        def set_value(value: float | None = None) -> None:
            if value is None:
                temperature.text = '-'
            else:
                temperature.text = f'{value:0.1f}°C'

        icon = Label(
            text='device_thermostat',
            color='#ffffff',
            font_name='material_symbols',
            font_size=dp(16),
            font_features='fill=0',
            size_hint=(None, 1),
            width=dp(12),
        )
        layout.add_widget(icon)
        layout.add_widget(temperature)

        return layout

    @cached_property
    def light_widget(self: MenuAppFooter) -> Label:
        light = Label(
            text='light_mode',
            color='#ffffff',
            font_name='material_symbols',
            font_size=dp(16),
            font_features='fill=0',
            size_hint=(None, 1),
            width=dp(16),
        )
        light.bind(
            texture_size=lambda light, texture_size: setattr(
                light,
                'width',
                texture_size[0],
            ),
        )

        @autorun(lambda state: state.sensors.light.value)
        def set_value(value: float | None = None) -> None:
            if value is None:
                light.color = (0.5, 0, 0, 1)
            else:
                v = min(value, 140) / 140
                light.color = (1, 1, 1, v)

        return light

    @cached_property
    def clock_widget(self: MenuAppFooter) -> Label:
        clock = Label(font_size=dp(20), size_hint=(None, 1), valign='middle')
        clock.bind(
            texture_size=lambda clock, texture_size: setattr(
                clock,
                'width',
                texture_size[0],
            ),
        )
        local_timzone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo

        def now() -> datetime.datetime:
            return datetime.datetime.now(local_timzone)

        def set_value(_: int | None = None) -> None:
            clock.text = now().strftime('%H:%M')

        def update(_: int | None = None) -> None:
            set_value()
            now_ = now()
            Clock.schedule_once(
                update,
                60 - now_.second - now_.microsecond / 1000000 + 0.05,
            )

        update()

        return clock

    @cached_property
    def footer(self: MenuAppFooter) -> Widget | None:
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

        home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))
        home_footer_layout.add_widget(self.clock_widget)
        home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))
        home_footer_layout.add_widget(self.temperature_widget)
        home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))
        home_footer_layout.add_widget(self.light_widget)
        home_footer_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))

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
        def render_icons(selector_result: Sequence[IconState]) -> None:
            icons = selector_result
            icons_layout.clear_widgets()
            for icon in list(reversed(icons))[:4]:
                label = Label(
                    text=icon.symbol,
                    color=icon.color,
                    font_name='material_symbols',
                    font_size=dp(20),
                    font_features='fill=0',
                    size_hint=(None, 1),
                    width=dp(22),
                )
                icons_layout.add_widget(label)
            icons_layout.add_widget(Widget(size_hint=(None, 1), width=dp(2)))
            icons_layout.bind(minimum_width=icons_layout.setter('width'))

        @autorun(lambda state: state.main.path)
        def handle_depth_change(path: Sequence[str]) -> None:
            is_fullscreen = (
                'TODO' in path
            )  # TODO(sassanh): Check if the application is fullscreen
            if not is_fullscreen:
                if normal_footer_layout in layout.children:
                    layout.remove_widget(normal_footer_layout)
                    layout.add_widget(home_footer_layout)
            elif home_footer_layout in layout.children:
                layout.remove_widget(home_footer_layout)
                layout.add_widget(normal_footer_layout)

        layout.add_widget(home_footer_layout)

        return layout
