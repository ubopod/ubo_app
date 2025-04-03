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


class SettingsServiceAction(SettingsAction):
    """Service action."""

    service_id: str


class SettingsStartServiceAction(SettingsServiceAction):
    """Start service action."""


class SettingsStopServiceAction(SettingsServiceAction):
    """Stop service action."""


class SettingsServiceSetStatusAction(SettingsServiceAction):
    """Set service status action."""

    is_active: bool


class SettingsServiceSetIsEnabledAction(SettingsServiceAction):
    """Set service enabled action."""

    is_enabled: bool


class SettingsServiceSetLogLevelAction(SettingsServiceAction):
    """Set service log level action."""

    log_level: int


class SettingsServiceSetShouldRestartAction(SettingsServiceAction):
    """Set service should restart action."""

    should_auto_restart: bool


class SettingsReportServiceErrorAction(SettingsServiceAction):
    """Report service error action."""

    error: ErrorReport


class SettingsClearServiceErrorsAction(SettingsServiceAction):
    """Clear service errors action."""


class SettingsEvent(BaseEvent):
    """Settings event."""


class SettingsSetDebugModeEvent(SettingsEvent):
    """Set debug mode event."""

    is_enabled: bool


class SettingsServiceEvent(SettingsEvent):
    """Service event."""

    service_id: str


class SettingsStartServiceEvent(SettingsServiceEvent):
    """Start service event."""

    delay: float = 0


class SettingsStopServiceEvent(SettingsServiceEvent):
    """Stop service event."""


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
    log_level: int
    should_auto_restart: bool
    errors: list[ErrorReport] = field(default_factory=list)


class SettingsState(Immutable):
    """Settings state."""

    is_debug_enabled: bool = False
    services: dict[str, ServiceState] = field(default_factory=dict)
