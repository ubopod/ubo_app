"""Status bar types for the dumb UI architecture.

These types consolidate header and footer state into a single source of truth.
"""

from __future__ import annotations

from immutable import Immutable


class StatusIconData(Immutable):
    """Status bar icon data for rendering."""

    symbol: str
    color: str  # Color string (e.g., 'white', '#ff0000')


class ProgressNotificationData(Immutable):
    """Progress notification for status bar rendering."""

    id: str
    progress: float | None  # None = indeterminate (spinner), 0-1 = progress ring
    color: str  # Color string


class StatusBarData(Immutable):
    """All data needed to render the status bar (header + footer).

    This consolidates header and footer state into a single source of truth.
    """

    # Header
    title: str = ''
    is_recording: bool = False
    is_replaying: bool = False
    is_recording_audio: bool = False
    progress_notifications: tuple[ProgressNotificationData, ...] = ()

    # Footer
    clock: str = ''  # "14:30"
    temperature: float | None = None
    light_level: float | None = None
    icons: tuple[StatusIconData, ...] = ()
