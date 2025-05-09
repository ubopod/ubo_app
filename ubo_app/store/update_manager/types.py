# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import field
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
    recent_versions: list[str] | None = None


class UpdateManagerRequestCheckAction(UpdateManagerAction): ...


class UpdateManagerReportFailedCheckAction(UpdateManagerAction): ...


class UpdateManagerRequestUpdateAction(UpdateManagerAction):
    version: str


class UpdateManagerEvent(BaseEvent): ...


class UpdateManagerCheckEvent(UpdateManagerEvent): ...


class UpdateManagerUpdateEvent(UpdateManagerEvent):
    version: str | None


class UpdateStatus(StrEnum):
    """Update status enum."""

    CHECKING = auto()
    FAILED_TO_CHECK = auto()
    UP_TO_DATE = auto()
    OUTDATED = auto()
    UPDATING = auto()


class UpdateManagerState(Immutable):
    """Version store."""

    current_version: str | None = None
    base_image_variant: str | None = None
    latest_version: str | None = None
    update_status: UpdateStatus = UpdateStatus.CHECKING
    recent_versions: list[str] = field(default_factory=list)
