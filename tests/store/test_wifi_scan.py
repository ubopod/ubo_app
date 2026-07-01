"""Tests for the Wi-Fi scan helpers in ``wifi_manager``.

Covers the security-type derivation from NetworkManager access-point flags and
the dedupe/sort behavior of ``get_available_networks``.

``wifi_manager`` imports ``sdbus`` / ``sdbus_async`` at module load, which are
only present on the device (and in the Docker test image), so this module is
skipped where those native deps are unavailable.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip('sdbus_async.networkmanager')

from ubo_app.store.services.wifi import WiFiType

_service_dir = str(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '030-wifi',
)
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

import wifi_manager  # type: ignore[import-not-found]  # noqa: E402


@pytest.mark.parametrize(
    ('flags', 'wpa_flags', 'rsn_flags', 'expected'),
    [
        (0, 0, 0, WiFiType.NOPASS),
        (0x1, 0, 0, WiFiType.WEP),
        (0x1, 0x100, 0, WiFiType.WPA),
        (0x1, 0, 0x100, WiFiType.WPA2),
        (0x1, 0x100, 0x100, WiFiType.WPA2),  # RSN takes precedence over WPA
    ],
)
def test_derive_wifi_type(
    flags: int,
    wpa_flags: int,
    rsn_flags: int,
    expected: WiFiType,
) -> None:
    """Security type is derived correctly from NM access-point flags."""
    assert (
        wifi_manager._derive_wifi_type(flags, wpa_flags, rsn_flags) == expected  # noqa: SLF001
    )


class _FakeAccessPoint:
    """Minimal stand-in whose properties resolve like the sdbus AccessPoint."""

    def __init__(
        self,
        ssid: bytes,
        strength: int,
        flags: int = 0,
        wpa_flags: int = 0,
        rsn_flags: int = 0,
    ) -> None:
        self._values: dict[str, Any] = {
            'ssid': ssid,
            'strength': strength,
            'flags': flags,
            'wpa_flags': wpa_flags,
            'rsn_flags': rsn_flags,
        }

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        value = self.__dict__['_values'][name]

        async def _coro() -> Any:  # noqa: ANN401
            return value

        return _coro()


def test_get_available_networks_dedup_and_sort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scanned networks are deduped to the strongest and sorted by signal."""
    access_points = [
        _FakeAccessPoint(b'Home', 40, flags=0x1, rsn_flags=0x100),
        _FakeAccessPoint(b'Home', 80, flags=0x1, rsn_flags=0x100),  # stronger dup
        _FakeAccessPoint(b'Cafe', 60),  # open
        _FakeAccessPoint(b'', 90),  # hidden / empty SSID -> skipped
    ]

    async def _fake_request_scan() -> None:
        return None

    async def _fake_get_access_points() -> list[Any]:
        return access_points

    monkeypatch.setattr(wifi_manager, 'request_scan', _fake_request_scan)
    monkeypatch.setattr(wifi_manager, 'get_access_points', _fake_get_access_points)

    networks = asyncio.run(wifi_manager.get_available_networks())

    # Empty SSID dropped, 'Home' deduped to its strongest, sorted by strength desc.
    assert [(n.ssid, n.strength, n.type) for n in networks] == [
        ('Home', 80, WiFiType.WPA2),
        ('Cafe', 60, WiFiType.NOPASS),
    ]
