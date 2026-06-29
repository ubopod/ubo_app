"""Tests for the WiFi-join QR payload builder shared by the hotspot flows.

``build_wifi_qr`` lives in ``ubo_app.utils.hotspot_qr`` (a pure helper used by
both the wifi connect notification and the web-ui captive notification).
"""

from __future__ import annotations

from ubo_app.utils.hotspot_qr import build_wifi_qr


def test_wifi_qr_basic() -> None:
    """A plain SSID/password produces a standard WPA WiFi-join payload."""
    assert build_wifi_qr('ubo-ab', 'secret') == 'WIFI:S:ubo-ab;T:WPA;P:secret;;'


def test_wifi_qr_escapes_special_chars() -> None:
    r"""Special characters (; : \) are backslash-escaped per the WiFi-QR spec."""
    assert build_wifi_qr('My;Net', 'pa:ss\\x') == r'WIFI:S:My\;Net;T:WPA;P:pa\:ss\\x;;'
