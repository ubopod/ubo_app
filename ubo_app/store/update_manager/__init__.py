# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from enum import StrEnum, auto

from immutable import Immutable
from redux import BaseAction, BaseEvent

UPDATE_MANAGER_NOTIFICATION_ID = 'ubo:update_manager'


class UpdateManagerAction(BaseAction): ...


class UpdateManagerSetVersionsAction(UpdateManagerAction):
    flash_notification: bool
    latest_version: str
    current_version: str
    serial_number: str


class UpdateManagerSetStatusAction(UpdateManagerAction):
    status: UpdateStatus


class UpdateManagerEvent(BaseEvent): ...


class UpdateManagerCheckEvent(UpdateManagerEvent): ...


class UpdateManagerUpdateEvent(UpdateManagerEvent): ...


class UpdateStatus(StrEnum):
    """Update status enum."""

    CHECKING = auto()
    FAILED_TO_CHECK = auto()
    UP_TO_DATE = auto()
    OUTDATED = auto()
    UPDATING = auto()


class UpdateManagerState(Immutable):
    """Version store."""

    serial_number: str | None = None
    current_version: str | None = None
    latest_version: str | None = None
    update_status: UpdateStatus = UpdateStatus.CHECKING
