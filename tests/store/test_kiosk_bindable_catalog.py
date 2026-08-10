"""Tests for the kiosk bindable action's parameter options.

`kiosk:set-output` is registered once and takes an output and a target as
parameters; these are the ``(value, label)`` choices its prompt offers. The
store types import normally; only the catalog needs a ``sys.path`` shim, since
the service directory (``055-kiosk``) is not an importable package (mirroring
``test_kiosk_config``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ubo_app.store.services.kiosk import UBO_WEBUI_DASHBOARD_ID, KioskDashboard

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    Ports = Sequence[tuple[str, str, str, str]]
    PortOptions = Callable[[Ports], list[tuple[str, str]]]
    TargetOptions = Callable[[Sequence[KioskDashboard]], list[tuple[str, str]]]


def _import_catalog() -> tuple[PortOptions, TargetOptions]:
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
        port_options,
        target_options,
    )

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return port_options, target_options


port_options, target_options = _import_catalog()

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


def test_port_options_offer_every_output() -> None:
    """The value is the state field name; the label is what the menu shows."""
    assert port_options(_PORTS) == [
        ('hdmi_a_1', 'HDMI-1'),
        ('hdmi_a_2', 'HDMI-2'),
    ]


def test_target_options_list_terminal_off_then_dashboards() -> None:
    """Terminal and off always available; dashboards follow, built-in included."""
    assert target_options((_WEBUI, _HA)) == [
        ('terminal', 'Terminal'),
        ('off', 'Off'),
        ('dash:ubo-webui', 'Ubo WebUI'),
        ('dash:ha', 'HA Dashboard'),
    ]


def test_target_options_without_dashboards_still_offer_terminal_and_off() -> None:
    """An output can always be turned off, even with nothing to browse."""
    assert target_options(()) == [('terminal', 'Terminal'), ('off', 'Off')]


def test_target_values_compose_registered_menu_action_ids() -> None:
    """The factory builds `kiosk:set:<port>:<target>`, so values are that tail.

    Guards the coupling to the ids registered by
    ``_register_kiosk_action_handlers`` / ``_register_dashboard_action_handlers``.
    """
    ports = [value for value, _label in port_options(_PORTS)]
    targets = [value for value, _label in target_options((_WEBUI,))]

    assert [f'kiosk:set:{port}:{target}' for port in ports for target in targets] == [
        'kiosk:set:hdmi_a_1:terminal',
        'kiosk:set:hdmi_a_1:off',
        'kiosk:set:hdmi_a_1:dash:ubo-webui',
        'kiosk:set:hdmi_a_2:terminal',
        'kiosk:set:hdmi_a_2:off',
        'kiosk:set:hdmi_a_2:dash:ubo-webui',
    ]


def test_duplicate_dashboard_names_get_distinguishable_labels() -> None:
    """Names are free text and can collide.

    The prompt's SELECT shows labels and maps the choice back to a value, so two
    dashboards sharing a name would otherwise be indistinguishable — and one of
    them unpickable.
    """
    duplicates = (
        KioskDashboard(id='a', name='Dashboard', url='http://a'),
        KioskDashboard(id='b', name='Dashboard', url='http://b'),
        KioskDashboard(id='c', name='Dashboard', url='http://c'),
    )

    options = target_options(duplicates)
    labels = [label for _value, label in options]

    assert len(set(labels)) == len(labels)
    assert labels[2:] == ['Dashboard', 'Dashboard (2)', 'Dashboard (3)']
