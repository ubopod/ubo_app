# ruff: noqa: D100
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

    protocol: str
    scancode: str


class InfraredSendCodeAction(InfraredAction):
    """Action to send an infrared code."""

    protocol: str
    scancode: str


class InfraredSetShouldPropagateAction(InfraredAction):
    """Action to set the should propagate keypad actions flag."""

    should_propagate: bool


class InfraredSetShouldReceiveAction(InfraredAction):
    """Action to set the should receive keypad actions flag."""

    should_receive: bool


class InfraredRegisterDeviceAction(InfraredAction):
    """Action to register a new infrared device."""


class InfraredSetIsRegisteringDeviceAction(InfraredAction):
    """Action to set the is registering device flag."""

    is_registering: bool


class InfraredSetRegistrationCodeAction(InfraredAction):
    """Action to set the registration code being tracked."""

    protocol: str
    scancode: str
    repetition_count: int


class InfraredSendCodeEvent(InfraredEvent):
    """Event to send an infrared code."""

    protocol: str
    scancode: str


class InfraredState(Immutable):
    """State of the infrared service."""

    should_propagate_keypad_actions: bool = field(
        default=read_from_persistent_store(
            'infrared_state:should_propagate_keypad_actions',
            default=False,
        ),
    )
    should_receive_keypad_actions: bool = field(
        default=read_from_persistent_store(
            'infrared_state:should_receive_keypad_actions',
            default=False,
        ),
    )
    is_registering_device: bool = False
    registration_signal_counts: dict[tuple[str, str], int] = field(default_factory=dict)
