# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from enum import Enum

from redux import BaseAction, BaseEvent, Immutable


class WiFiType(str, Enum):
    """Represents the types of WiFi security protocols."""

    WEP = 'WEP'
    WPA = 'WPA'
    WPA2 = 'WPA2'
    nopass = 'NOPASS'


class WiFiConnection(Immutable):
    """Represents a WiFi connection.

    Attributes
    ----------
        ssid (str): The SSID of the WiFi network.
        password (str | None): The password for the WiFi network. Defaults to None.
        type (str | None): The type of the WiFi connection. Defaults to None.
    """

    ssid: str
    password: str | None = None
    type: str | None = None


class WiFiAction(BaseAction):
    ...


class WiFiUpdateActionPayload(Immutable):
    """Represents the payload for a WiFi update action.

    Attributes
    ----------
        connections (list[WiFiConnection]): List of WiFi connections.
        is_on (bool): Indicates whether WiFi is turned on or off.
        current_connection (WiFiConnection | None): The currently active WiFi connection, or None if no connection is active.
    """

    connections: list[WiFiConnection]
    is_on: bool
    current_connection: WiFiConnection | None


class WiFiUpdateAction(WiFiAction):
    payload: WiFiUpdateActionPayload


class WiFiState(Immutable):
    """Represents the state of the WiFi connections.

    Attributes
    ----------
        connections (list[WiFiConnection]): List of WiFi connections.
        is_on (bool): Indicates whether WiFi is turned on or off.
        current_connection (WiFiConnection | None): The currently active
        WiFi connection, or None if no connection is active.
    """

    connections: list[WiFiConnection]
    is_on: bool
    current_connection: WiFiConnection | None


class WiFiEvent(BaseEvent):
    ...


class WiFiCreateEventPayload(Immutable):
    """Represents the payload for a WiFi create event.

    Attributes
    ----------
        connection (WiFiConnection): The WiFi connection information.
    """

    connection: WiFiConnection


class WiFiCreateEvent(WiFiEvent):
    """Represents an event for creating a WiFi connection.

    Attributes
    ----------
        payload (WiFiCreateEventPayload): The payload containing the details of
        the WiFi connection to be created.
    """

    payload: WiFiCreateEventPayload


class WiFiUpdateEvent(WiFiEvent):
    """Represents an event for updating WiFi information."""

    payload: None = None
