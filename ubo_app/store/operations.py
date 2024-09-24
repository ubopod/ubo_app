"""Type definitions for the Redux store operations."""

from __future__ import annotations

from typing import TypeAlias

from redux import (
    BaseEvent,
    CombineReducerAction,
    FinishAction,
    InitAction,
)

from ubo_app.store.core import MainAction, MainEvent
from ubo_app.store.services.audio import AudioAction, AudioEvent
from ubo_app.store.services.camera import CameraAction, CameraEvent
from ubo_app.store.services.display import DisplayAction, DisplayEvent
from ubo_app.store.services.docker import DockerAction
from ubo_app.store.services.ip import IpAction, IpEvent
from ubo_app.store.services.keypad import KeypadAction, KeypadEvent
from ubo_app.store.services.lightdm import LightDMAction
from ubo_app.store.services.notifications import (
    NotificationsAction,
    NotificationsEvent,
)
from ubo_app.store.services.rgb_ring import RgbRingAction
from ubo_app.store.services.rpi_connect import RPiConnectAction
from ubo_app.store.services.sensors import SensorsAction
from ubo_app.store.services.ssh import SSHAction
from ubo_app.store.services.users import UsersAction, UsersEvent
from ubo_app.store.services.voice import VoiceAction
from ubo_app.store.services.vscode import VSCodeAction
from ubo_app.store.services.wifi import WiFiAction, WiFiEvent
from ubo_app.store.status_icons import StatusIconsAction
from ubo_app.store.update_manager import UpdateManagerAction


class ScreenshotEvent(BaseEvent):
    """Event for taking a screenshot."""


class SnapshotEvent(BaseEvent):
    """Event for taking a snapshot of the store."""


UboAction: TypeAlias = (
    # Core Actions
    CombineReducerAction
    | StatusIconsAction
    | UpdateManagerAction
    | MainAction
    | InitAction
    | FinishAction
    # Services Actions
    | AudioAction
    | CameraAction
    | DisplayAction
    | DockerAction
    | IpAction
    | KeypadAction
    | LightDMAction
    | NotificationsAction
    | RgbRingAction
    | RPiConnectAction
    | SensorsAction
    | SSHAction
    | UsersAction
    | VoiceAction
    | VSCodeAction
    | WiFiAction
)
UboEvent: TypeAlias = (
    # Core Events
    MainEvent
    | ScreenshotEvent
    # Services Events
    | AudioEvent
    | CameraEvent
    | DisplayEvent
    | IpEvent
    | KeypadEvent
    | NotificationsEvent
    | SnapshotEvent
    | UsersEvent
    | WiFiEvent
)
