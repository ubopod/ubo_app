"""Tests for ``write_kiosk_config`` reporting whether it changed anything.

The generated config and the store can drift apart: the files are only rewritten
on a selection change or a kiosk start, so a boot that restores a selection the
generated script disagrees with leaves the two out of step with nothing to
reconcile them. Telling the caller whether the write actually changed the files
is what lets startup fix that without restarting the kiosk — and reloading
whatever is on screen — every single time the app starts.

Filesystem-touching, unlike its sibling ``test_kiosk_config``, so the module
paths are redirected at a ``tmp_path`` per test.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from ubo_app.store.services.kiosk import (
    UBO_WEBUI_DASHBOARD_ID,
    KioskDashboard,
    KioskPortRole,
    KioskPortSelection,
    KioskPortSelections,
)


def _import_config() -> Any:  # noqa: ANN401
    """Import the service-dir ``kiosk_config`` module via a ``sys.path`` shim.

    Unlike the pure-generator tests this keeps the module object, because the
    paths it writes to are module-level constants the fixture has to redirect.
    """
    service_dir = str(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '055-kiosk',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    import kiosk_config  # type: ignore[import-not-found]

    return kiosk_config


_WEBUI = KioskDashboard(
    id=UBO_WEBUI_DASHBOARD_ID,
    name='Ubo WebUI',
    url='http://localhost:4321',
)
_DASHBOARDS = (_WEBUI,)

_BROWSER = KioskPortSelections(
    hdmi_a_1=KioskPortSelection(
        role=KioskPortRole.BROWSER,
        dashboard_id=UBO_WEBUI_DASHBOARD_ID,
    ),
    hdmi_a_2=KioskPortSelection(role=KioskPortRole.TERMINAL),
)
_TERMINAL = KioskPortSelections(
    hdmi_a_1=KioskPortSelection(role=KioskPortRole.TERMINAL),
    hdmi_a_2=KioskPortSelection(role=KioskPortRole.TERMINAL),
)


@pytest.fixture
def kiosk_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:  # noqa: ANN401
    """Return the ``kiosk_config`` module, redirected to write into ``tmp_path``."""
    module = _import_config()
    config_dir = tmp_path / 'ubo-kiosk'
    monkeypatch.setattr(module, 'KIOSK_CONFIG_DIR', config_dir)
    monkeypatch.setattr(module, 'WESTON_INI_PATH', config_dir / 'weston.ini')
    monkeypatch.setattr(
        module,
        'CLIENTS_SCRIPT_PATH',
        config_dir / 'kiosk-clients.sh',
    )
    return module


def test_first_write_reports_a_change(kiosk_config: Any) -> None:  # noqa: ANN401
    """Writing into an empty config directory is a change."""
    assert kiosk_config.write_kiosk_config(_BROWSER, _DASHBOARDS) is True
    assert kiosk_config.WESTON_INI_PATH.exists()
    assert kiosk_config.CLIENTS_SCRIPT_PATH.exists()


def test_rewriting_the_same_config_reports_no_change(
    kiosk_config: Any,  # noqa: ANN401
) -> None:
    """The second identical write must not claim to have changed anything.

    This is the one that keeps a restart — and a visible reload of whatever the
    kiosk is showing — off the startup path when nothing is actually wrong.
    """
    kiosk_config.write_kiosk_config(_BROWSER, _DASHBOARDS)

    assert kiosk_config.write_kiosk_config(_BROWSER, _DASHBOARDS) is False


def test_changed_selection_reports_a_change(kiosk_config: Any) -> None:  # noqa: ANN401
    """A different selection rewrites the files and says so."""
    kiosk_config.write_kiosk_config(_TERMINAL, _DASHBOARDS)

    assert kiosk_config.write_kiosk_config(_BROWSER, _DASHBOARDS) is True
    assert 'chromium' in kiosk_config.CLIENTS_SCRIPT_PATH.read_text()


def test_config_left_stale_on_disk_is_detected(kiosk_config: Any) -> None:  # noqa: ANN401
    """The actual bug: on-disk config disagreeing with the desired selection.

    A physical keypad press once switched HDMI-1 to Terminal and the generated
    script followed, but the persisted selection was later restored to the
    browser. Startup has to notice that the script on disk is not the one the
    state asks for.
    """
    kiosk_config.write_kiosk_config(_TERMINAL, _DASHBOARDS)
    assert 'chromium' not in kiosk_config.CLIENTS_SCRIPT_PATH.read_text()

    # State now says browser; the reconcile must report the disagreement.
    assert kiosk_config.write_kiosk_config(_BROWSER, _DASHBOARDS) is True


def test_launcher_script_stays_executable(kiosk_config: Any) -> None:  # noqa: ANN401
    """An unchanged write must not drop the executable bit weston relies on."""
    kiosk_config.write_kiosk_config(_BROWSER, _DASHBOARDS)
    kiosk_config.write_kiosk_config(_BROWSER, _DASHBOARDS)

    assert kiosk_config.CLIENTS_SCRIPT_PATH.stat().st_mode & 0o111
