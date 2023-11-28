# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from kivy.app import Builder
from ubo_gui.page import PageWidget

from ubo_app.store import dispatch
from ubo_app.store.camera import (
    CameraStartViewfinderAction,
    CameraStartViewfinderActionPayload,
)

if TYPE_CHECKING:
    from ubo_gui.menu.types import ActionItem

# Regular expression pattern
# WIFI:S:<SSID>;T:<WEP|WPA|blank>;P:<PASSWORD>;H:<true|false|blank>;;
barcode_pattern = r"""WIFI:S:(?P<SSID>[^;]*);(?:T:(?P<Type>(?i:WEP|WPA|WPA2|nopass));)\
?(?:P:(?P<Password>[^;]*);)?(?:H:(?P<Hidden>(?i:true|false));)?"""


class WiFiSetupPage(PageWidget):
    def get_item(self: WiFiSetupPage, index: int) -> ActionItem | None:
        if index == 2:
            return {
                'label': 'start',
                'is_short': True,
                'icon': 'camera',
                'action': lambda: dispatch(
                    CameraStartViewfinderAction(
                        payload=CameraStartViewfinderActionPayload(
                            barcode_pattern=barcode_pattern,
                        ),
                    ),
                ),
            }
        return super().get_item(index)


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('setup.kv').resolve().as_posix(),
)
