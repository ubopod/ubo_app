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


# Note: Settings category icons are registered dynamically by the
# application via register_category_icon() in view_registry.py.
