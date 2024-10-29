"""Settings state module."""

from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class SettingsAction(BaseAction):
    """Settings action."""


class SettingsToggleDebugModeAction(SettingsAction):
    """Toggle debug mode action."""


class SettingsEvent(BaseEvent):
    """Settings event."""


class SettingsSetDebugModeEvent(SettingsEvent):
    """Set debug mode event."""

    is_enabled: bool


class SettingsState(Immutable):
    """Settings state."""

    is_debug_enabled: bool = False
