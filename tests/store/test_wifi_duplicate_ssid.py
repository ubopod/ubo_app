"""Tests for WiFi action-handler registration with duplicate SSIDs.

NetworkManager can report several profiles under one SSID (band-split access
points, duplicate saved profiles). Action IDs are keyed by SSID alone, so the
registration pass has to collapse them first or it raises on the duplicate and
kills the `update_wifi_dynamic_menu` autorun.

Regression test for UBO-APP-QA.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from ubo_app.store.core.action_registry import (
    clear_all_actions,
    get_registered_actions,
)
from ubo_app.store.services.wifi import ConnectionState, WiFiConnection

SERVICES_ROOT = Path(__file__).resolve().parents[2] / 'ubo_app' / 'services'
WIFI_SERVICE = SERVICES_ROOT / '030-wifi'


@contextmanager
def _service_imports(service: Path) -> Iterator[None]:
    """Import bare service modules as *service* would see them.

    Services share bare module names — every one of them has a `constants` —
    and in production `UboServiceFinder` keys them per service. A plain test
    process has no such finder, so whichever service loaded first wins the
    name. Evict every already-loaded service module for the duration, then put
    `sys.modules` and `sys.path` back exactly as they were so the rest of the
    suite is unaffected.
    """
    saved_modules = dict(sys.modules)
    saved_path = list(sys.path)

    for name, module in list(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and str(SERVICES_ROOT) in filename:
            del sys.modules[name]

    sys.path.insert(0, str(service))
    try:
        yield
    finally:
        for name in set(sys.modules) - set(saved_modules):
            del sys.modules[name]
        sys.modules.update(saved_modules)
        sys.path[:] = saved_path


def _import_wifi_page_helpers() -> tuple:
    """Import `_deduplicate_by_ssid` and friends from the WiFi page module."""
    with _service_imports(WIFI_SERVICE):
        from pages.main import (  # pyright: ignore[reportMissingImports]
            _cache,
            _deduplicate_by_ssid,
            _register_wifi_action_handlers,
        )

    return _deduplicate_by_ssid, _register_wifi_action_handlers, _cache


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Clear the action registry before each test."""
    clear_all_actions()


class TestDeduplicateBySsid:
    """Tests for `_deduplicate_by_ssid`."""

    def test_collapses_duplicate_ssids(self) -> None:
        """Two profiles under one SSID collapse to a single entry."""
        deduplicate, _, _ = _import_wifi_page_helpers()

        result = deduplicate(
            [
                WiFiConnection(ssid='Home', state=ConnectionState.DISCONNECTED),
                WiFiConnection(ssid='Home', state=ConnectionState.DISCONNECTED),
            ],
        )

        assert len(result) == 1
        assert result[0].ssid == 'Home'

    def test_keeps_distinct_ssids(self) -> None:
        """Distinct SSIDs all survive."""
        deduplicate, _, _ = _import_wifi_page_helpers()

        result = deduplicate(
            [
                WiFiConnection(ssid='Home', state=ConnectionState.CONNECTED),
                WiFiConnection(ssid='Cafe', state=ConnectionState.DISCONNECTED),
            ],
        )

        assert {connection.ssid for connection in result} == {'Home', 'Cafe'}

    def test_liveliest_profile_wins(self) -> None:
        """A connected duplicate beats a disconnected one, whatever the order."""
        deduplicate, _, _ = _import_wifi_page_helpers()

        for states in (
            (ConnectionState.DISCONNECTED, ConnectionState.CONNECTED),
            (ConnectionState.CONNECTED, ConnectionState.DISCONNECTED),
        ):
            result = deduplicate(
                [WiFiConnection(ssid='Home', state=state) for state in states],
            )
            assert len(result) == 1
            assert result[0].state == ConnectionState.CONNECTED

    def test_connecting_beats_unknown(self) -> None:
        """The ranking runs through the whole enum, not just connected/other."""
        deduplicate, _, _ = _import_wifi_page_helpers()

        result = deduplicate(
            [
                WiFiConnection(ssid='Home', state=ConnectionState.UNKNOWN),
                WiFiConnection(ssid='Home', state=ConnectionState.CONNECTING),
            ],
        )

        assert result[0].state == ConnectionState.CONNECTING

    def test_empty_input(self) -> None:
        """An empty sequence yields an empty list."""
        deduplicate, _, _ = _import_wifi_page_helpers()

        assert deduplicate([]) == []


class TestRegisterWifiActionHandlers:
    """Tests for `_register_wifi_action_handlers`."""

    def test_duplicate_ssid_does_not_raise(self) -> None:
        """Duplicate SSIDs register once instead of raising ValueError."""
        _, register_handlers, cache = _import_wifi_page_helpers()
        cache.connection_fingerprint = None

        register_handlers(
            [
                WiFiConnection(ssid='TP-Link_F8A4', state=ConnectionState.CONNECTED),
                WiFiConnection(
                    ssid='TP-Link_F8A4',
                    state=ConnectionState.DISCONNECTED,
                ),
            ],
        )

        registered = get_registered_actions()
        assert 'wifi:open-connection:TP-Link_F8A4' in registered
        assert 'wifi:connect:TP-Link_F8A4' in registered
        assert 'wifi:disconnect:TP-Link_F8A4' in registered
        assert 'wifi:forget:TP-Link_F8A4' in registered

    def test_registers_every_distinct_ssid(self) -> None:
        """Deduplication must not drop a legitimately distinct network."""
        _, register_handlers, cache = _import_wifi_page_helpers()
        cache.connection_fingerprint = None

        register_handlers(
            [
                WiFiConnection(ssid='Home', state=ConnectionState.CONNECTED),
                WiFiConnection(ssid='Home', state=ConnectionState.DISCONNECTED),
                WiFiConnection(ssid='Cafe', state=ConnectionState.DISCONNECTED),
            ],
        )

        registered = get_registered_actions()
        assert 'wifi:open-connection:Home' in registered
        assert 'wifi:open-connection:Cafe' in registered
