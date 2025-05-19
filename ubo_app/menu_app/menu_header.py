# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import math
from functools import cached_property
from typing import TYPE_CHECKING

from kivy.animation import Animation
from kivy.clock import mainthread
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.relativelayout import RelativeLayout
from redux import AutorunOptions
from ubo_gui.app import UboApp
from ubo_gui.progress_ring import ProgressRingWidget
from ubo_gui.spinner import SpinnerWidget

from ubo_app.store.main import store

if TYPE_CHECKING:
    from kivy.uix.widget import Widget

    from ubo_app.store.services.notifications import Notification


class MenuAppHeader(UboApp):
    notification_widgets: dict[str, tuple[Notification, Widget]]
    progress_layout: BoxLayout

    @mainthread
    def set_notification_widgets(
        self: MenuAppHeader,
        notifications: list[Notification],
    ) -> None:
        for notification in notifications:
            if notification.progress is None:
                if notification.id in self.notification_widgets:
                    self.progress_layout.remove_widget(
                        self.notification_widgets[notification.id][1],
                    )
                    del self.notification_widgets[notification.id]
            elif math.isnan(notification.progress):
                if notification.id not in self.notification_widgets or not isinstance(
                    widget := self.notification_widgets[notification.id][1],
                    SpinnerWidget,
                ):
                    [_, widget] = self.notification_widgets[notification.id] = (
                        notification,
                        SpinnerWidget(
                            font_size=dp(16),
                            size_hint=(None, None),
                            pos_hint={'center_y': 0.5},
                            height=dp(16),
                            width=dp(16),
                        ),
                    )
                widget.color = notification.color
            else:
                if notification.id not in self.notification_widgets or not isinstance(
                    widget := self.notification_widgets[notification.id][1],
                    ProgressRingWidget,
                ):
                    [_, widget] = self.notification_widgets[notification.id] = (
                        notification,
                        ProgressRingWidget(
                            background_color=(0.3, 0.3, 0.3, 1),
                            height=dp(16),
                            band_width=dp(7),
                            size_hint=(None, None),
                            pos_hint={'center_y': 0.5},
                        ),
                    )
                widget.progress = notification.progress
                widget.color = notification.color

        for id in set(self.notification_widgets) - {
            notification.id for notification in notifications
        }:
            del self.notification_widgets[id]

        self.progress_layout.clear_widgets()

        for item in sorted(
            self.notification_widgets.values(),
            key=lambda item: item[0].timestamp,
        ):
            self.progress_layout.add_widget(item[1])

        self.progress_layout.width = self.progress_layout.minimum_width

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

    @mainthread
    def handle_is_recording_change(
        self: MenuAppHeader,
        is_recording: bool,  # noqa: FBT001
    ) -> None:
        if is_recording:
            if self.recording_sign not in self.header_content.children:
                self.header_content.add_widget(self.recording_sign)
                self.sign_animation.start(self.recording_sign)
        elif self.recording_sign in self.header_content.children:
            self.header_content.remove_widget(self.recording_sign)
            self.sign_animation.cancel(self.recording_sign)

    @mainthread
    def handle_is_replaying_change(
        self: MenuAppHeader,
        is_replaying: bool,  # noqa: FBT001
    ) -> None:
        if is_replaying:
            if self.replaying_sign not in self.header_content.children:
                self.header_content.add_widget(self.replaying_sign)
                self.sign_animation.start(self.replaying_sign)
        elif self.replaying_sign in self.header_content.children:
            self.header_content.remove_widget(self.replaying_sign)
            self.sign_animation.cancel(self.replaying_sign)

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

        store.autorun(
            lambda state: [
                notification
                for notification in state.notifications.notifications
                if notification.progress is not None
            ],
            options=AutorunOptions(keep_ref=False),
        )(self.set_notification_widgets)

        store.autorun(
            lambda state: state.main.is_header_visible,
            options=AutorunOptions(keep_ref=False),
        )(self.handle_is_header_visible_change)

        store.autorun(
            lambda state: state.main.is_recording,
            options=AutorunOptions(keep_ref=False),
        )(self.handle_is_recording_change)

        store.autorun(
            lambda state: state.main.is_replaying,
            options=AutorunOptions(keep_ref=False),
        )(self.handle_is_replaying_change)

        return self.header_layout
