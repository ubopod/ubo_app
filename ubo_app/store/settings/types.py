"""Settings state module."""

from __future__ import annotations

from dataclasses import field
from pathlib import Path

from immutable import Immutable
from redux import BaseAction, BaseEvent

ROOT_PATH = Path(__file__).parent.parent.parent


class SettingsAction(BaseAction):
    """Settings action."""


class SettingsToggleDebugModeAction(SettingsAction):
    """Toggle debug mode action."""


class SettingsSetServicesAction(SettingsAction):
    """Start service action."""

    services: dict[str, ServiceState]
    gap_duration: float


class SettingsStartServiceAction(SettingsAction):
    """Start service action."""

    service_id: str


class SettingsStopServiceAction(SettingsAction):
    """Stop service action."""

    service_id: str


class SettingsServiceSetStatusAction(SettingsAction):
    """Set service status action."""

    service_id: str
    is_active: bool


class SettingsReportServiceErrorAction(SettingsAction):
    """Report service error action."""

    service_id: str
    error: ErrorReport


class SettingsClearServiceErrorsAction(SettingsAction):
    """Clear service errors action."""

    service_id: str


class SettingsEvent(BaseEvent):
    """Settings event."""


class SettingsSetDebugModeEvent(SettingsEvent):
    """Set debug mode event."""

    is_enabled: bool


class SettingsStartServiceEvent(SettingsEvent):
    """Start service event."""

    service_id: str
    delay: float = 0


class SettingsStopServiceEvent(SettingsEvent):
    """Stop service event."""

    service_id: str


class ErrorReport(Immutable):
    """Error report."""

    timestamp: float
    message: str


class ServiceState(Immutable):
    """Service state."""

    id: str
    label: str
    is_active: bool
    is_enabled: bool
    errors: list[ErrorReport] = field(default_factory=list)


class SettingsState(Immutable):
    """Settings state."""

    is_debug_enabled: bool = False
    services: dict[str, ServiceState] | None = None
