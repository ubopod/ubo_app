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


class MenuScrollDirection(StrEnum):
    """Direction of menu scroll actions."""

    UP = 'up'
    DOWN = 'down'


# Settings category icons mapping
SETTINGS_ICONS: dict[SettingsCategory, str] = {
    SettingsCategory.NETWORK: '󰛳',
    SettingsCategory.REMOTE: '󰑔',
    SettingsCategory.SYSTEM: '󰒔',
    SettingsCategory.HARDWARE: '',
    SettingsCategory.ASSISTANT: '󰚩',
    SettingsCategory.DOCKER: '󰡨',
    SettingsCategory.ACCESSIBILITY: '󰙋',
}
