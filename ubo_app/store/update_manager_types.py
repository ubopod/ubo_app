# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from enum import Enum, auto

from immutable import Immutable
from redux import BaseAction


class SetLatestVersionAction(BaseAction):
    latest_version: str


class SetUpdateStatusAction(BaseAction):
    status: UpdateStatus


class UpdateStatus(Enum):
    """Update status enum."""

    CHECKING = auto()
    FAILED_TO_CHECK = auto()
    UP_TO_DATE = auto()
    OUTDATED = auto()
    UPDATING = auto()


class VersionStatus(Immutable):
    """Version store."""

    latest_version: str | None = None
    update_status: UpdateStatus = UpdateStatus.CHECKING
