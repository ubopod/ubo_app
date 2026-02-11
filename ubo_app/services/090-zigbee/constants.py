"""Constants for the Zigbee service."""

from __future__ import annotations

# Status icon configuration
ZIGBEE_STATE_ICON_ID = 'zigbee:state'
ZIGBEE_STATE_ICON_PRIORITY = -10

# Menu priority (lower = higher in list)
ZIGBEE_MENU_PRIORITY = 1

# Icons for coordinator and device states
ICON_ZIGBEE = '󰵁'  # Zigbee icon
ICON_COORDINATOR_CONNECTED = '󰛁'  # Connected coordinator
ICON_COORDINATOR_SAVED = '󰛀'  # Has saved network but not connected
ICON_COORDINATOR_NEW = '󱘖'  # New/unknown coordinator
ICON_DEVICE_AVAILABLE = '󰔡'  # Device online
ICON_DEVICE_UNAVAILABLE = '󰔤'  # Device offline
ICON_PAIRING = '󰐕'  # Pairing mode active
ICON_SENSOR = '󱖠'  # Sensor readings
ICON_SWITCH = '󰔏'  # Switch/toggle
ICON_LIGHT = '󰌵'  # Light
ICON_BACKUP = '󰁯'  # Backup
ICON_SETTINGS = '󰒔'  # Settings
ICON_REFRESH = '󰑓'  # Refresh/retry
ICON_DELETE = '󰆴'  # Delete
ICON_RENAME = '󰏫'  # Rename
ICON_RESET = '󰜺'  # Reset network
ICON_SUCCESS = '󰄬'  # Checkmark/success
ICON_LOADING = '\uf110'  # SpinnerWidget spinner icon
