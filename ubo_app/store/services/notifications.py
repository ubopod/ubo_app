# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import sys
from dataclasses import field
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from immutable import Immutable
from redux import BaseAction, BaseEvent
from ubo_gui.constants import SECONDARY_COLOR_LIGHT
from ubo_gui.menu.types import ActionItem

from ubo_app.constants import NOTIFICATIONS_FLASH_TIME
from ubo_app.store.dispatch_action import DispatchItem

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from kivy.graphics.context_instructions import Color


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


def _default_icon() -> str:
    # WARNING: Dirty hack ahead
    # This is to set the default value of `icon` based on the provided/default value of
    # `importance`
    parent_frame = sys._getframe().f_back  # noqa: SLF001
    if not parent_frame:
        return ''
    return IMPORTANCE_ICONS[parent_frame.f_locals.get('importance', Importance.LOW)]


def _default_color() -> str:
    # WARNING: Dirty hack ahead
    # This is to set the default value of `color` based on the provided/default value of
    # `importance`
    parent_frame = sys._getframe().f_back  # noqa: SLF001
    if not parent_frame:
        return ''
    return IMPORTANCE_COLORS[parent_frame.f_locals.get('importance', Importance.LOW)]


class Chime(StrEnum):
    ADD = 'add'
    DONE = 'done'
    FAILURE = 'failure'
    VOLUME_CHANGE = 'volume'


class NotificationActionItem(ActionItem):
    background_color: Color | Callable[[], Color] = SECONDARY_COLOR_LIGHT
    dismiss_notification: bool = False


class NotificationDispatchItem(DispatchItem, NotificationActionItem): ...


class NotificationExtraInformation(Immutable):
    text: str
    piper_text: str | None = None
    picovoice_text: str | None = None


class Notification(Immutable):
    id: str = field(default_factory=lambda: uuid4().hex)
    title: str
    content: str
    extra_information: NotificationExtraInformation | None = None
    importance: Importance = Importance.LOW
    chime: Chime | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    is_read: bool = False
    sender: str | None = None
    actions: list[NotificationActionItem | NotificationDispatchItem] = field(
        default_factory=list,
    )
    icon: str = field(default_factory=_default_icon)
    color: str = field(default_factory=_default_color)
    expiration_timestamp: datetime | None = None
    display_type: NotificationDisplayType = NotificationDisplayType.NOT_SET
    flash_time: float = NOTIFICATIONS_FLASH_TIME
    dismissable: bool = True
    dismiss_on_close: bool = False
    on_close: Callable[[], Any] | None = None
    blink: bool = True
    progress: float | None = None
    progress_weight: float = 1


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
