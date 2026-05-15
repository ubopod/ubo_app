"""Enum types for the core store module."""

from __future__ import annotations

from enum import StrEnum


class SettingsCategory(StrEnum):
    """Categories for settings menu organization."""

    NETWORK = 'Network'
    REMOTE = 'Remote'
    SYSTEM = 'System'
    HARDWARE = 'Hardware'
    ASSISTANT = 'Assistant'
    DOCKER = 'Docker'
    ACCESSIBILITY = 'Accessibility'
    LOCALIZATION = 'Localization'


class MenuScrollDirection(StrEnum):
    """Direction of menu scroll actions."""

    UP = 'up'
    DOWN = 'down'


# Note: Settings category icons are defined in constants.py as
# SETTINGS_CATEGORY_ICONS and registered via register_category_icon().
