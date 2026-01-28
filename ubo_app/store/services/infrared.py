# ruff: noqa: D100
from __future__ import annotations

import json
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


class InfraredAddDeviceAction(InfraredAction):
    """Action to add a registered infrared device."""

    name: str
    protocol: str
    scancode: str


class InfraredRemoveDeviceAction(InfraredAction):
    """Action to remove a registered infrared device."""

    protocol: str
    scancode: str


class InfraredSendCodeEvent(InfraredEvent):
    """Event to send an infrared code."""

    protocol: str
    scancode: str


class InfraredDeviceRegistrationStartedEvent(InfraredEvent):
    """Event when device registration is started."""


class InfraredDeviceRegistrationCompleteEvent(InfraredEvent):
    """Event when a device signal has been registered 5 times."""

    protocol: str
    scancode: str


class InfraredDevice(Immutable):
    """Represents a registered infrared device."""

    name: str
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
    original_should_receive_keypad_actions: bool | None = None
    registered_devices: list[InfraredDevice] = field(
        default_factory=lambda: read_from_persistent_store(
            'infrared_state:registered_devices',
            default=[],
            mapper=lambda value: [
                InfraredDevice(**device) if isinstance(device, dict) else device
                for device in (json.loads(value) if isinstance(value, str) else value)
            ]
            if value
            else [],
        ),
    )
