# ruff: noqa: D100, D101
from __future__ import annotations

from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.constants import WEB_UI_LISTEN_PORT
from ubo_app.utils.persistent_store import read_from_persistent_store

UBO_WEBUI_DASHBOARD_ID = 'ubo-webui'


class KioskPortRole(StrEnum):
    """Role assigned to a single HDMI port."""

    BROWSER = 'browser'
    TERMINAL = 'terminal'
    OFF = 'off'


class KioskDashboard(Immutable):
    """A named browser dashboard the kiosk can point an HDMI output at."""

    id: str
    name: str
    url: str


class KioskPortSelection(Immutable):
    """What a single HDMI output shows: a role plus (for BROWSER) a dashboard."""

    role: KioskPortRole = KioskPortRole.TERMINAL
    dashboard_id: str | None = None


class KioskPortSelections(Immutable):
    hdmi_a_1: KioskPortSelection = field(
        default_factory=lambda: KioskPortSelection(
            role=KioskPortRole.BROWSER,
            dashboard_id=UBO_WEBUI_DASHBOARD_ID,
        ),
    )
    hdmi_a_2: KioskPortSelection = field(
        default_factory=lambda: KioskPortSelection(role=KioskPortRole.TERMINAL),
    )


class KioskAction(BaseAction): ...


class KioskEvent(BaseEvent): ...


class KioskUpdateStateAction(KioskAction):
    is_active: bool | None = None
    is_enabled: bool | None = None
    is_installed: bool | None = None
    is_installing: bool | None = None
    connected_ports: tuple[str, ...] | None = None


class KioskClearEnabledStateAction(KioskAction): ...


class KioskSetPortSelectionAction(KioskAction):
    port: str
    role: KioskPortRole
    dashboard_id: str | None = None


class KioskAddDashboardAction(KioskAction):
    id: str
    name: str
    url: str


class KioskDeleteDashboardAction(KioskAction):
    dashboard_id: str


class KioskRotatePortAction(KioskAction):
    port: str


class KioskApplyConfigEvent(KioskEvent): ...


def _ubo_webui_dashboard() -> KioskDashboard:
    return KioskDashboard(
        id=UBO_WEBUI_DASHBOARD_ID,
        name='Ubo WebUI',
        url=f'http://localhost:{WEB_UI_LISTEN_PORT}',
    )


def _restore_port_selection(
    key: str,
    default: KioskPortSelection,
) -> KioskPortSelection:
    """Restore a port selection, falling back to ``default`` if it isn't one.

    ``output_type`` is a hint, not a guarantee: ``Store.load_object`` returns
    scalars as-is before it ever consults the requested type, so a value
    written under an older schema — these keys once held a bare role string —
    passes straight through and lands in state as a ``str``. Nothing notices
    until an autorun reads ``.role`` off it, at which point the exception fires
    on every state change and the kiosk menus silently stop updating.
    """
    restored = read_from_persistent_store(
        key,
        output_type=KioskPortSelection,
        default=default,
    )
    if not isinstance(restored, KioskPortSelection):
        return default
    return restored


def _restore_port_selections() -> KioskPortSelections:
    return KioskPortSelections(
        hdmi_a_1=_restore_port_selection(
            'kiosk:hdmi_a_1',
            KioskPortSelection(
                role=KioskPortRole.BROWSER,
                dashboard_id=UBO_WEBUI_DASHBOARD_ID,
            ),
        ),
        hdmi_a_2=_restore_port_selection(
            'kiosk:hdmi_a_2',
            KioskPortSelection(role=KioskPortRole.TERMINAL),
        ),
    )


def _restore_dashboards() -> tuple[KioskDashboard, ...]:
    user_dashboards = read_from_persistent_store(
        'kiosk:dashboards',
        output_type=tuple[KioskDashboard, ...],
        default=(),
    )
    return (_ubo_webui_dashboard(), *user_dashboards)


class KioskState(Immutable):
    is_active: bool = False
    is_enabled: bool = False
    is_installed: bool = False
    is_installing: bool = False
    port_selections: KioskPortSelections = field(
        default_factory=_restore_port_selections,
    )
    dashboards: tuple[KioskDashboard, ...] = field(default_factory=_restore_dashboards)
    connected_ports: tuple[str, ...] = ()
