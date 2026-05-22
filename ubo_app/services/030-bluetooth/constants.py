# ruff: noqa: D100
from __future__ import annotations

# Status icon
BLUETOOTH_STATE_ICON_ID = 'bluetooth:state'
BLUETOOTH_STATE_ICON_PRIORITY = -13

# Dynamic menu IDs
BLUETOOTH_SETTINGS_MENU_ID = 'bluetooth:settings'
BLUETOOTH_DISCOVERED_MENU_ID = 'bluetooth:discovered'
BLUETOOTH_PAIRED_MENU_ID = 'bluetooth:paired'

# Pairing agent
BLUETOOTH_AGENT_PATH = '/com/ubo/bluetooth/agent'
BLUETOOTH_AGENT_CAPABILITY = 'DisplayYesNo'

# While the discovered-devices menu is open, the device list is refreshed
# (and BlueZ is re-polled) every this many seconds.
DISCOVERY_POLL_INTERVAL = 1.5

# How long to wait for the user to confirm a pairing passkey.
PAIRING_CONFIRMATION_TIMEOUT = 30

# Status-bar / menu icons
BLUETOOTH_ICON = '󰂯'
BLUETOOTH_CONNECTED_ICON = '󰂱'
BLUETOOTH_OFF_ICON = '󰂲'


def get_device_icon(icon_hint: str | None) -> str:
    """Map a BlueZ ``Icon`` property hint to a display glyph."""
    if not icon_hint:
        return BLUETOOTH_ICON
    if icon_hint.startswith('audio'):
        return '󰋋'
    if icon_hint == 'input-keyboard':
        return '󰌌'
    if icon_hint == 'input-mouse':
        return '󰍽'
    if icon_hint.startswith('input-gaming'):
        return '󰊴'
    if icon_hint == 'phone':
        return '󰏲'
    if icon_hint == 'computer':
        return '󰟀'
    return BLUETOOTH_ICON
