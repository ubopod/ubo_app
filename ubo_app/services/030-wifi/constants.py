# ruff: noqa: D100, D103
import math

WIFI_STATE_ICON_ID = 'wifi:state'
WIFI_STATE_ICON_PRIORITY = -12
SIGNAL_ICONS = ['󰤯', '󰤟', '󰤢', '󰤥', '󰤨']

# Dynamic menu IDs for dumb UI architecture
WIFI_SETTINGS_MENU_ID = 'wifi:settings'
WIFI_CONNECTIONS_MENU_ID = 'wifi:connections'
# Ad-hoc on-device list of scanned networks shown during hotspot onboarding.
WIFI_SCAN_MENU_ID = 'wifi:hotspot-scan'


def get_signal_icon(strength: float) -> str:
    return SIGNAL_ICONS[math.floor(strength / 100 * 4.999)]
