"""Menu item styling parameters (Kivy-free)."""

from __future__ import annotations

from typing import Literal, TypeAlias

from ubo_app.colors import SUCCESS_COLOR

ItemParameters: TypeAlias = dict[Literal['background_color', 'color', 'icon'], str]

SELECTED_ITEM_PARAMETERS: ItemParameters = {
    'background_color': SUCCESS_COLOR,
    'icon': '󰱒',
}
UNSELECTED_ITEM_PARAMETERS: ItemParameters = {
    'icon': '󰄱',
}
