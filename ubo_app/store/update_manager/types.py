# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from enum import StrEnum, auto

from immutable import Immutable
from redux import BaseAction, BaseEvent

UPDATE_MANAGER_NOTIFICATION_ID = 'ubo:update_manager'
UPDATE_MANAGER_SECOND_PHASE_NOTIFICATION_ID = 'ubo:update_manager:phase-2'


class UpdateManagerAction(BaseAction): ...


class UpdateManagerSetVersionsAction(UpdateManagerAction):
    flash_notification: bool
    current_version: str
    base_image_variant: str
    latest_version: str
    serial_number: str


class UpdateManagerSetStatusAction(UpdateManagerAction):
    status: UpdateStatus


class UpdateManagerSetUpdateServiceStatusAction(UpdateManagerAction):
    is_active: bool


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
    base_image_variant: str | None = None
    latest_version: str | None = None
    update_status: UpdateStatus = UpdateStatus.CHECKING
    is_update_service_active: bool = False
