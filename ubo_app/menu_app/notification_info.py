# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.properties import StringProperty
from ubo_gui.page import PageWidget


class NotificationInfo(PageWidget):
    text: str = StringProperty(default='')


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('notification_info.kv').resolve().as_posix(),
)
