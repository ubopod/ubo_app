"""WiFi page widgets for the GUI client."""

from __future__ import annotations

import pathlib
from enum import StrEnum
from typing import Any

from kivy.lang.builder import Builder
from kivy.properties import BooleanProperty, StringProperty
from ubo_gui.prompt import PromptWidget

from ubo_gui_client.gui_utils import UboPageWidget, UboPromptWidget
from ubo_gui_client.pages import get_grpc_client


class ConnectionState(StrEnum):
    """WiFi connection state enum (local copy for GUI client)."""

    CONNECTED = 'Connected'
    CONNECTING = 'Connecting'
    DISCONNECTED = 'Disconnected'
    UNKNOWN = 'Unknown'


class WiFiConnectionPage(UboPromptWidget):
    """WiFi connection page - shows connect/disconnect/delete options."""

    ssid: str = StringProperty()
    state: ConnectionState = StringProperty(defaultvalue=ConnectionState.UNKNOWN)

    def first_option_callback(self) -> None:
        """Handle first option (connect/disconnect).

        Dispatches connect or disconnect action via gRPC.
        """
        from ubo_bindings.ubo.v1 import Action, ExecuteMenuActionAction

        client = get_grpc_client()
        if self.state == ConnectionState.CONNECTED:
            action_id = f'wifi:disconnect:{self.ssid}'
        else:
            action_id = f'wifi:connect:{self.ssid}'
        client.dispatch_raw(
            Action(
                execute_menu_action_action=ExecuteMenuActionAction(
                    action_id=action_id,
                ),
            ),
        )

    def second_option_callback(self) -> None:
        """Handle second option (delete/forget).

        Dispatches the app-button action which closes the page and forgets.
        """
        from ubo_bindings.ubo.v1 import Action, ExecuteMenuActionAction

        client = get_grpc_client()
        client.dispatch_raw(
            Action(
                execute_menu_action_action=ExecuteMenuActionAction(
                    action_id='app-button:wifi:connection-page:2',
                ),
            ),
        )

    def update(self, *_: tuple[Any, ...]) -> None:
        """Update UI based on connection state."""
        if self.state == ConnectionState.CONNECTED:
            self.first_option_label = 'Disconnect'
            self.first_option_icon = '󰖪'
            self.first_option_color = 'black'
            self.first_option_background_color = (
                PromptWidget.first_option_background_color.defaultvalue
            )
            self.icon = '󰖩'
        elif self.state == ConnectionState.DISCONNECTED:
            self.first_option_label = 'Connect'
            self.first_option_icon = '󰖩'
            self.first_option_color = 'black'
            self.first_option_background_color = (
                PromptWidget.first_option_background_color.defaultvalue
            )
            self.icon = '󰖪'
        elif self.state == ConnectionState.CONNECTING:
            self.first_option_label = 'Connecting...'
            self.first_option_icon = ''
            self.first_option_color = 'white'
            self.first_option_background_color = 'black'
            self.icon = ''
        elif self.state == ConnectionState.UNKNOWN:
            self.first_option_label = ''
            self.first_option_icon = ''
            self.first_option_color = 'white'
            self.first_option_background_color = 'black'
            self.icon = ''

    def __init__(self, **kwargs: object) -> None:
        """Initialize the WiFi connection page."""
        super().__init__(**kwargs)
        self.title = None
        self.prompt = f'SSID: {self.ssid}'
        self.first_option_is_short = False
        self.second_option_label = 'Delete'
        self.second_option_icon = '󰆴'
        self.second_option_is_short = False

        self.bind(state=self.update)
        self.update()


class WiFiCreateConnectionPage(UboPageWidget):
    """WiFi create connection page - shows creating status."""

    creating = BooleanProperty(defaultvalue=False)


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('wifi_pages.kv').resolve().as_posix(),
)
