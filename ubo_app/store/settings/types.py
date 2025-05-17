"""Settings state module."""

from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from pathlib import Path

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.constants import DEBUG_BETA_VERSIONS, DEBUG_PDB_SIGNAL, DEBUG_VISUAL
from ubo_app.utils.persistent_store import read_from_persistent_store

ROOT_PATH = Path(__file__).parent.parent.parent


class ServicesStatus(StrEnum):
    """Services status enum."""

    LOADING = 'loading'
    READY = 'ready'


class SettingsAction(BaseAction):
    """Settings action."""


class SettingsTogglePdbSignalAction(SettingsAction):
    """Toggle PDB signal action."""


class SettingsToggleVisualDebugAction(SettingsAction):
    """Toggle visual debug mode action."""


class SettingsToggleBetaVersionsAction(SettingsAction):
    """Toggle beta versions action."""


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

    pdb_signal: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'settings:pdb_signal',
            default=DEBUG_PDB_SIGNAL,
        ),
    )
    visual_debug: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'settings:visual_debug',
            default=DEBUG_VISUAL,
        ),
    )
    beta_versions: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'settings:beta_versions',
            default=DEBUG_BETA_VERSIONS,
        ),
    )
    services: dict[str, ServiceState] = field(default_factory=dict)
    services_status: ServicesStatus = ServicesStatus.LOADING
