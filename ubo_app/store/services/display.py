# ruff: noqa: D100, D101
from __future__ import annotations

from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class DisplayBlankTimeout(StrEnum):
    """Available display blank timeout options."""

    ONE_MINUTE = 'one_minute'
    FIVE_MINUTES = 'five_minutes'
    TEN_MINUTES = 'ten_minutes'
    THIRTY_MINUTES = 'thirty_minutes'
    ONE_HOUR = 'one_hour'
    OFF = 'off'

    def get_timeout_seconds(self: DisplayBlankTimeout) -> float | None:
        """Get timeout in seconds, None for OFF."""
        mapping = {
            DisplayBlankTimeout.ONE_MINUTE: 60.0,
            DisplayBlankTimeout.FIVE_MINUTES: 300.0,
            DisplayBlankTimeout.TEN_MINUTES: 600.0,
            DisplayBlankTimeout.THIRTY_MINUTES: 1800.0,
            DisplayBlankTimeout.ONE_HOUR: 3600.0,
            DisplayBlankTimeout.OFF: None,
        }
        return mapping[self]

    def get_label(self: DisplayBlankTimeout) -> str:
        """Get human-readable label."""
        labels = {
            DisplayBlankTimeout.ONE_MINUTE: '1 minute',
            DisplayBlankTimeout.FIVE_MINUTES: '5 minutes',
            DisplayBlankTimeout.TEN_MINUTES: '10 minutes',
            DisplayBlankTimeout.THIRTY_MINUTES: '30 minutes',
            DisplayBlankTimeout.ONE_HOUR: '1 hour',
            DisplayBlankTimeout.OFF: 'Off',
        }
        return labels[self]


class DisplayAction(BaseAction): ...


class DisplayEvent(BaseEvent): ...


class DisplayPauseAction(DisplayAction): ...


class DisplayResumeAction(DisplayAction): ...


class DisplayRedrawAction(DisplayAction): ...


class DisplayBlankAction(DisplayAction): ...


class DisplayUnblankAction(DisplayAction): ...


class DisplayUpdateActivityAction(DisplayAction): ...


class DisplaySetBlankTimeoutAction(DisplayAction):
    timeout: DisplayBlankTimeout


class DisplayRedrawEvent(DisplayEvent): ...


class DisplayBlankEvent(DisplayEvent): ...


class DisplayUnblankEvent(DisplayEvent): ...


class DisplayRenderEvent(DisplayEvent):
    timestamp: float
    data: bytes
    rectangle: tuple[int, int, int, int]
    density: float


class DisplayCompressedRenderEvent(DisplayEvent):
    timestamp: float
    compressed_data: bytes
    rectangle: tuple[int, int, int, int]
    density: float


class DisplayState(Immutable):
    is_paused: bool = False
    is_blanked: bool = False
    last_activity_time: float | None = None
    selected_blank_timeout: DisplayBlankTimeout = read_from_persistent_store(
        'display:selected_blank_timeout',
        mapper=lambda value: DisplayBlankTimeout(value),
        default=DisplayBlankTimeout.TEN_MINUTES,
    )
