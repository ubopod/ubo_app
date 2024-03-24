# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
import math

WIFI_STATE_ICON_ID = 'wifi:state'
WIFI_STATE_ICON_PRIORITY = -12
SIGNAL_ICONS = ['󰤯', '󰤟', '󰤢', '󰤥', '󰤨']


def get_signal_icon(strength: float) -> str:
    return SIGNAL_ICONS[math.floor(strength / 100 * 4.999)]
