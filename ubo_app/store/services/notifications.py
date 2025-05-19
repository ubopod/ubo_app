# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import socket
from dataclasses import field
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from immutable import Immutable
from redux import BaseAction, BaseEvent
from ubo_gui.menu.types import ActionItem

from ubo_app.colors import SECONDARY_COLOR_LIGHT
from ubo_app.constants import NOTIFICATIONS_FLASH_TIME
from ubo_app.store.ubo_actions import UboApplicationItem, UboDispatchItem
from ubo_app.utils.dataclass import default_provider

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from kivy.graphics.context_instructions import Color

    from ubo_app.store.services.speech_synthesis import ReadableInformation


class Importance(StrEnum):
    CRITICAL = auto()
    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()


IMPORTANCE_ICONS = {
    Importance.CRITICAL: '󰅚',
    Importance.HIGH: '󰀪',
    Importance.MEDIUM: '',
    Importance.LOW: '󰌶',
}

IMPORTANCE_COLORS = {
    Importance.CRITICAL: '#D32F2F',
    Importance.HIGH: '#FFA000',
    Importance.MEDIUM: '#FFEB3B',
    Importance.LOW: '#2196F3',
}


class NotificationDisplayType(StrEnum):
    NOT_SET = auto()
    BACKGROUND = auto()
    FLASH = auto()
    STICKY = auto()


class Chime(StrEnum):
    ADD = 'add'
    DONE = 'done'
    FAILURE = 'failure'
    VOLUME_CHANGE = 'volume'


class NotificationActionItem(ActionItem):
    background_color: Color | Callable[[], Color] = SECONDARY_COLOR_LIGHT
    dismiss_notification: bool = False
    close_notification: bool = True


class NotificationApplicationItem(UboApplicationItem):
    background_color: Color | Callable[[], Color] = SECONDARY_COLOR_LIGHT
    dismiss_notification: bool = False
    close_notification: bool = True


class NotificationDispatchItem(UboDispatchItem, NotificationActionItem): ...


class Notification(Immutable):
    id: str = field(default_factory=lambda: uuid4().hex)
    title: str
    content: str
    extra_information: ReadableInformation | None = None
    importance: Importance = Importance.LOW
    chime: Chime | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    is_read: bool = False
    sender: str | None = None
    actions: list[NotificationActionItem | NotificationApplicationItem] = field(
        default_factory=list,
    )
    icon: str = field(
        default_factory=default_provider(
            ['importance'],
            lambda importance: IMPORTANCE_ICONS[importance],
        ),
    )
    color: str = field(
        default_factory=default_provider(
            ['importance'],
            lambda importance: IMPORTANCE_COLORS[importance],
        ),
    )
    expiration_timestamp: datetime | None = None
    display_type: NotificationDisplayType = NotificationDisplayType.NOT_SET
    flash_time: float = NOTIFICATIONS_FLASH_TIME
    show_dismiss_action: bool = True
    dismiss_on_close: bool = False
    on_close: Callable[[], Any] | None = None
    blink: bool = True
    progress: float | None = None
    progress_weight: float = 1

    def __post_init__(self) -> None:
        """Replace `{{hostname}}` with the current hostname."""
        object.__setattr__(
            self,
            'title',
            self.title.replace(
                '{{hostname}}',
                f'{socket.gethostname()}.local',
            ),
        )
        object.__setattr__(
            self,
            'content',
            self.content.replace(
                '{{hostname}}',
                f'{socket.gethostname()}.local',
            ),
        )


class NotificationsAction(BaseAction): ...


class NotificationsAddAction(NotificationsAction):
    notification: Notification


class NotificationsDisplayAction(NotificationsAction):
    notification: Notification
    index: int | None = None
    count: int | None = None


class NotificationsClearAction(NotificationsAction):
    notification: Notification


class NotificationsClearByIdAction(NotificationsAction):
    id: str


class NotificationsClearAllAction(NotificationsAction): ...


class NotificationsEvent(BaseEvent): ...


class NotificationsClearEvent(NotificationsEvent):
    notification: Notification


class NotificationsDisplayEvent(NotificationsEvent):
    notification: Notification
    index: int | None = None
    count: int | None = None


class NotificationsState(Immutable):
    notifications: Sequence[Notification]
    unread_count: int
    progress: float | None = None
