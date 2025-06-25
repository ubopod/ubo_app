# ruff: noqa: D100, D101
from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty

from ubo_app.utils.gui import UboPageWidget


class NotificationInfo(UboPageWidget):
    text: str = StringProperty()

    def go_down(self: NotificationInfo) -> None:
        """Scroll down the notification list."""
        self.ids.slider.animated_value -= dp(100)

    def go_up(self: NotificationInfo) -> None:
        """Scroll up the notification list."""
        self.ids.slider.animated_value += dp(100)


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('notification_info.kv').resolve().as_posix(),
)
