# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import field

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class InfraredAction(BaseAction):
    """Base action for infrared service."""


class InfraredEvent(BaseEvent):
    """Base event for infrared service."""


class InfraredHandleReceivedCodeAction(InfraredAction):
    """Carries the received infrared code."""

    code: tuple[int, ...]


class InfraredSendCodeAction(InfraredAction):
    """Action to send an infrared code."""

    code: tuple[int, ...]


class InfraredSetShouldPropagateAction(InfraredAction):
    """Action to set the should propagate keypad actions flag."""

    should_propagate: bool


class InfraredSetShouldReceiveAction(InfraredAction):
    """Action to set the should receive keypad actions flag."""

    should_receive: bool


class InfraredSendCodeEvent(InfraredEvent):
    """Event to send an infrared code."""

    code: tuple[int, ...]


class InfraredState(Immutable):
    """State of the infrared service."""

    should_propagate_keypad_actions: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'infrared_state:should_propagate_keypad_actions',
            default=False,
        ),
    )
    should_receive_keypad_actions: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'infrared_state:should_receive_keypad_actions',
            default=False,
        ),
    )
