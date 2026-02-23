# ruff: noqa: D100, D101, D102
from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from kivy.animation import Animation
from kivy.clock import mainthread
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.relativelayout import RelativeLayout
from ubo_gui.app import UboApp

if TYPE_CHECKING:
    from kivy.uix.widget import Widget


class MenuAppHeader(UboApp):
    notification_widgets: dict[str, tuple[object, Widget]]
    progress_layout: BoxLayout

    @mainthread
    def handle_is_header_visible_change(
        self: MenuAppHeader,
        is_header_visible: bool,  # noqa: FBT001
    ) -> None:
        if is_header_visible:
            if self.header_content not in self.header_layout.children:
                self.header_layout.add_widget(self.header_content)
        elif self.header_content in self.header_layout.children:
            self.header_layout.remove_widget(self.header_content)

    @cached_property
    def header(self: MenuAppHeader) -> Widget | None:
        self.header_content = RelativeLayout()

        original_header = super().header
        if isinstance(original_header, Label):
            original_header.bind(size=original_header.setter('text_size'))
            original_header.halign = 'center'
            original_header.valign = 'center'
            original_header.shorten = True

        if not original_header:
            return None
        original_header.pos = (0, 0)
        self.header_content.add_widget(original_header)

        self.progress_layout = BoxLayout(
            orientation='horizontal',
            padding=dp(4),
            spacing=dp(2),
        )
        self.header_content.add_widget(self.progress_layout)

        self.recording_sign = Label(
            text='󰑊',
            font_size=dp(20),
            color=(1, 0, 0, 1),
            pos_hint={'right': 1},
            size_hint=(None, 1),
        )
        self.recording_sign.bind(texture_size=self.recording_sign.setter('size'))
        self.replaying_sign = Label(
            text='󰑙',
            font_size=dp(20),
            color=(0, 1, 0, 1),
            pos_hint={'right': 1},
            size_hint=(None, 1),
        )
        self.replaying_sign.bind(texture_size=self.replaying_sign.setter('size'))
        self.sign_animation = (
            Animation(opacity=1, duration=0.1)
            + Animation(duration=1)
            + Animation(opacity=0, duration=0.1)
            + Animation(duration=0.5)
        )
        self.sign_animation.repeat = True

        self.notification_widgets = {}

        self.header_layout = BoxLayout()
        self.header_layout.add_widget(self.header_content)

        # Header visibility is controlled by ViewRenderer via gRPC data

        return self.header_layout
