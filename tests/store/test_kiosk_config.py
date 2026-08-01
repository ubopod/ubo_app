"""Tests for the pure Weston kiosk config generators.

These assert the generated ``weston.ini`` and launcher-script strings across
selection combinations without touching the device or filesystem.

The store types import normally; only the config generators need a ``sys.path``
shim, since the service directory (``055-kiosk``) is not an importable package.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ubo_app.store.services.kiosk import (
    UBO_WEBUI_DASHBOARD_ID,
    KioskDashboard,
    KioskPortRole,
    KioskPortSelection,
    KioskPortSelections,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    GenerateConfig = Callable[
        [KioskPortSelections, tuple[KioskDashboard, ...]],
        str,
    ]


def _import_config() -> tuple[str, str, GenerateConfig, GenerateConfig]:
    """Import the service-dir ``kiosk_config`` generators via a ``sys.path`` shim.

    Records ``sys.modules`` before the import and drops anything newly loaded
    afterwards so integration/flow tests are unaffected by the bare
    ``kiosk_config`` module name.
    """
    modules_before = set(sys.modules)

    service_dir = str(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '055-kiosk',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from kiosk_config import (  # type: ignore[import-not-found]
        CHROMIUM_APP_ID_PREFIX,
        FOOT_APP_ID_PREFIX,
        generate_clients_script,
        generate_weston_ini,
    )

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return (
        CHROMIUM_APP_ID_PREFIX,
        FOOT_APP_ID_PREFIX,
        generate_clients_script,
        generate_weston_ini,
    )


(
    CHROMIUM_APP_ID_PREFIX,
    FOOT_APP_ID_PREFIX,
    generate_clients_script,
    generate_weston_ini,
) = _import_config()

_WEBUI = KioskDashboard(
    id=UBO_WEBUI_DASHBOARD_ID,
    name='Ubo WebUI',
    url='http://localhost:4321',
)
_HA = KioskDashboard(id='ha', name='HA Dashboard', url='http://ha.local:8123')
_DEFAULT_DASHBOARDS = (_WEBUI, _HA)


def _selections(
    role1: KioskPortRole,
    role2: KioskPortRole,
    *,
    dash1: str | None = None,
    dash2: str | None = None,
) -> KioskPortSelections:
    return KioskPortSelections(
        hdmi_a_1=KioskPortSelection(role=role1, dashboard_id=dash1),
        hdmi_a_2=KioskPortSelection(role=role2, dashboard_id=dash2),
    )


def test_weston_ini_default_selections_pin_apps_to_outputs() -> None:
    """Browser on HDMI-A-1, terminal on HDMI-A-2 → matching app-ids pins."""
    ini = generate_weston_ini(KioskPortSelections(), _DEFAULT_DASHBOARDS)

    assert 'shell=kiosk-shell.so' in ini
    assert 'name=HDMI-A-1' in ini
    assert f'app-ids={CHROMIUM_APP_ID_PREFIX}-hdmi_a_1' in ini
    assert 'name=HDMI-A-2' in ini
    assert f'app-ids={FOOT_APP_ID_PREFIX}-hdmi_a_2' in ini
    assert '[autolaunch]' in ini
    assert 'mode=off' not in ini


def test_weston_ini_off_selection_sets_mode_off() -> None:
    """An OFF port is disabled with mode=off and gets no app-ids pin."""
    ini = generate_weston_ini(
        _selections(
            KioskPortRole.BROWSER,
            KioskPortRole.OFF,
            dash1=UBO_WEBUI_DASHBOARD_ID,
        ),
        _DEFAULT_DASHBOARDS,
    )

    assert 'mode=off' in ini
    assert f'app-ids={CHROMIUM_APP_ID_PREFIX}-hdmi_a_1' in ini
    assert f'app-ids={FOOT_APP_ID_PREFIX}' not in ini


def test_clients_script_browser_and_terminal() -> None:
    """Both clients present → foot backgrounded and a Chromium restart loop."""
    script = generate_clients_script(KioskPortSelections(), _DEFAULT_DASHBOARDS)

    assert script.startswith('#!/bin/bash')
    assert f'--app-id={FOOT_APP_ID_PREFIX}-hdmi_a_2' in script
    assert 'while true; do' in script
    assert f'--class={CHROMIUM_APP_ID_PREFIX}-hdmi_a_1' in script
    assert 'localhost:4321' in script
    assert script.rstrip().endswith('wait')
    # Kiosk hardening: suppress the focus-stealing crash-restore/first-run UI,
    # and clear the crash markers before each (unclean-restart-prone) launch.
    assert '--disable-session-crashed-bubble' in script
    assert '--no-first-run' in script
    assert 'exited_cleanly' in script


def test_clients_script_two_browsers_use_distinct_urls() -> None:
    """Two browser ports at different dashboards get distinct app-ids + URLs."""
    script = generate_clients_script(
        _selections(
            KioskPortRole.BROWSER,
            KioskPortRole.BROWSER,
            dash1=UBO_WEBUI_DASHBOARD_ID,
            dash2='ha',
        ),
        _DEFAULT_DASHBOARDS,
    )

    assert 'foot' not in script
    assert f'--class={CHROMIUM_APP_ID_PREFIX}-hdmi_a_1' in script
    assert f'--class={CHROMIUM_APP_ID_PREFIX}-hdmi_a_2' in script
    assert 'http://localhost:4321' in script
    assert 'http://ha.local:8123' in script
    # Each browser gets its own profile dir, else Chromium's per-profile
    # singleton lock makes the two instances collide and reload-loop.
    assert '--user-data-dir' in script
    assert 'chromium-hdmi_a_1' in script
    assert 'chromium-hdmi_a_2' in script


def test_clients_script_two_terminals_use_distinct_app_ids() -> None:
    """Both ports on terminal → one foot per output with distinct app-ids.

    A single shared foot instance would only ever show on one screen, leaving
    the other blank; each output needs its own pinned surface.
    """
    script = generate_clients_script(
        _selections(KioskPortRole.TERMINAL, KioskPortRole.TERMINAL),
        _DEFAULT_DASHBOARDS,
    )
    ini = generate_weston_ini(
        _selections(KioskPortRole.TERMINAL, KioskPortRole.TERMINAL),
        _DEFAULT_DASHBOARDS,
    )

    assert f'--app-id={FOOT_APP_ID_PREFIX}-hdmi_a_1' in script
    assert f'--app-id={FOOT_APP_ID_PREFIX}-hdmi_a_2' in script
    assert script.count('foot ') == 2
    # Each output pins its own foot surface.
    assert f'app-ids={FOOT_APP_ID_PREFIX}-hdmi_a_1' in ini
    assert f'app-ids={FOOT_APP_ID_PREFIX}-hdmi_a_2' in ini
    assert 'while true; do' not in script
    assert script.rstrip().endswith('wait')


def test_clients_script_all_off_idles() -> None:
    """No clients → the script idles so Weston stays up."""
    script = generate_clients_script(
        _selections(KioskPortRole.OFF, KioskPortRole.OFF),
        _DEFAULT_DASHBOARDS,
    )

    assert 'foot' not in script
    assert 'while true; do' not in script
    assert script.rstrip().endswith('sleep infinity')
