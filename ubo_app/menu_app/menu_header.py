# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import math
from functools import cached_property
from typing import TYPE_CHECKING

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
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
                    self.notification_widgets[notification.id][1],
                    SpinnerWidget,
                ):
                    self.notification_widgets[notification.id] = (
                        notification,
                        SpinnerWidget(
                            font_size=dp(16),
                            size_hint=(None, None),
                            pos_hint={'center_y': 0.5},
                            height=dp(16),
                            width=dp(16),
                        ),
                    )
                self.notification_widgets[notification.id][1].color = notification.color
            else:
                if notification.id not in self.notification_widgets or not isinstance(
                    self.notification_widgets[notification.id][1],
                    ProgressRingWidget,
                ):
                    self.notification_widgets[notification.id] = (
                        notification,
                        ProgressRingWidget(
                            background_color=(0.3, 0.3, 0.3, 1),
                            height=dp(16),
                            band_width=dp(7),
                            size_hint=(None, None),
                            pos_hint={'center_y': 0.5},
                        ),
                    )
                self.notification_widgets[notification.id][
                    1
                ].progress = notification.progress
                self.notification_widgets[notification.id][1].color = notification.color

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

        return self.header_layout
