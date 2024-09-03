# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.relativelayout import RelativeLayout
from ubo_gui.app import UboApp
from ubo_gui.progress_ring import ProgressRingWidget

from ubo_app.store.main import store

if TYPE_CHECKING:
    from kivy.uix.widget import Widget

    from ubo_app.store.services.notifications import Notification


class MenuAppHeader(UboApp):
    @cached_property
    def header(self: MenuAppHeader) -> Widget | None:
        self.header_layout = RelativeLayout()

        original_header = super().header

        if not original_header:
            return None
        original_header.pos = (0, 0)
        self.header_layout.add_widget(original_header)

        progress_layout = BoxLayout(
            orientation='horizontal',
            padding=dp(4),
            spacing=dp(2),
        )
        self.header_layout.add_widget(progress_layout)

        @store.autorun(
            lambda state: [
                notification
                for notification in state.notifications.notifications
                if notification.progress is not None
            ],
        )
        def _(notifications: list[Notification]) -> None:
            for i in range(len(notifications)):
                if i < len(progress_layout.children):
                    progress_layout.children[i].progress = notifications[i].progress
                    progress_layout.children[i].color = notifications[i].color
                else:
                    progress_layout.add_widget(
                        ProgressRingWidget(
                            background_color=(0.3, 0.3, 0.3, 1),
                            color=notifications[i].color,
                            progress=notifications[i].progress,
                            height=dp(16),
                            band_width=dp(7),
                            size_hint=(None, None),
                            pos_hint={'center_y': 0.5},
                        ),
                    )
            for _ in range(len(notifications), len(progress_layout.children)):
                progress_layout.remove_widget(progress_layout.children[-1])

            progress_layout.width = progress_layout.minimum_width

        return self.header_layout
