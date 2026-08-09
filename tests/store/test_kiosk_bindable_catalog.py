"""Tests for the pure kiosk bindable-action catalog.

These assert the ``(key, label)`` entries offered to the bindable-actions
registry — the pool the voice-command and Infrared "Add Keys" dropdowns are
built from. The store types import normally; only the catalog needs a
``sys.path`` shim, since the service directory (``055-kiosk``) is not an
importable package (mirroring ``test_kiosk_config``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ubo_app.store.services.kiosk import UBO_WEBUI_DASHBOARD_ID, KioskDashboard

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    Ports = Sequence[tuple[str, str, str, str]]
    StaticEntries = Callable[[Ports], list[tuple[str, str]]]
    DashboardEntries = Callable[
        [Sequence[KioskDashboard], Ports],
        list[tuple[str, str]],
    ]


def _import_catalog() -> tuple[StaticEntries, DashboardEntries]:
    """Import the service-dir ``bindable_catalog`` via a ``sys.path`` shim.

    Records ``sys.modules`` before the import and drops anything newly loaded
    afterwards so integration/flow tests are unaffected by the bare
    ``bindable_catalog`` module name.
    """
    modules_before = set(sys.modules)

    service_dir = str(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '055-kiosk',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from bindable_catalog import (  # type: ignore[import-not-found]
        dashboard_bindable_entries,
        static_bindable_entries,
    )

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return static_bindable_entries, dashboard_bindable_entries


static_bindable_entries, dashboard_bindable_entries = _import_catalog()

# Mirrors ``setup.PORTS`` — the real table is passed in by the service so it
# isn't duplicated in the catalog module.
_PORTS: Ports = (
    ('hdmi_a_1', 'hdmi-a-1', 'HDMI-A-1', 'HDMI-1'),
    ('hdmi_a_2', 'hdmi-a-2', 'HDMI-A-2', 'HDMI-2'),
)

_WEBUI = KioskDashboard(
    id=UBO_WEBUI_DASHBOARD_ID,
    name='Ubo WebUI',
    url='http://localhost:4321',
)
_HA = KioskDashboard(id='ha', name='HA Dashboard', url='http://ha.local:8123')


def test_static_entries_cover_terminal_and_off_per_port() -> None:
    """Every port offers a terminal and an off entry, keyed by its menu action."""
    entries = dict(static_bindable_entries(_PORTS))

    assert entries == {
        'kiosk:set:hdmi_a_1:terminal': 'Kiosk: Terminal on HDMI-1',
        'kiosk:set:hdmi_a_1:off': 'Kiosk: Turn Off HDMI-1',
        'kiosk:set:hdmi_a_2:terminal': 'Kiosk: Terminal on HDMI-2',
        'kiosk:set:hdmi_a_2:off': 'Kiosk: Turn Off HDMI-2',
    }


def test_dashboard_entries_cover_every_dashboard_port_pair() -> None:
    """One entry per (dashboard, port), including the built-in Web UI."""
    entries = dict(dashboard_bindable_entries((_WEBUI, _HA), _PORTS))

    assert entries == {
        'kiosk:set:hdmi_a_1:dash:ubo-webui': 'Kiosk: Show Ubo WebUI on HDMI-1',
        'kiosk:set:hdmi_a_2:dash:ubo-webui': 'Kiosk: Show Ubo WebUI on HDMI-2',
        'kiosk:set:hdmi_a_1:dash:ha': 'Kiosk: Show HA Dashboard on HDMI-1',
        'kiosk:set:hdmi_a_2:dash:ha': 'Kiosk: Show HA Dashboard on HDMI-2',
    }


def test_dashboard_entries_are_empty_without_dashboards() -> None:
    """No dashboards means nothing to bind — the static entries still stand."""
    assert dashboard_bindable_entries((), _PORTS) == []


def test_duplicate_dashboard_names_get_unique_labels() -> None:
    """Free-text names can collide; the registry rejects a reused label.

    ``register_bindable_action`` raises when another key already holds a label,
    and that would propagate out of the dashboards autorun — so repeats are
    suffixed in dashboard order.
    """
    duplicates = (
        KioskDashboard(id='a', name='Dashboard', url='http://a'),
        KioskDashboard(id='b', name='Dashboard', url='http://b'),
        KioskDashboard(id='c', name='Dashboard', url='http://c'),
    )

    entries = dashboard_bindable_entries(duplicates, _PORTS)
    labels = [label for _key, label in entries]

    assert len(set(labels)) == len(labels)
    assert 'Kiosk: Show Dashboard on HDMI-1' in labels
    assert 'Kiosk: Show Dashboard (2) on HDMI-1' in labels
    assert 'Kiosk: Show Dashboard (3) on HDMI-2' in labels


def test_entry_keys_are_unique_across_static_and_dashboard_sets() -> None:
    """Keys double as menu-action ids, so the two sets must not overlap."""
    keys = [
        *(key for key, _label in static_bindable_entries(_PORTS)),
        *(key for key, _label in dashboard_bindable_entries((_WEBUI, _HA), _PORTS)),
    ]

    assert len(set(keys)) == len(keys)
