"""Tests for the hardware-free WiFi input-form schemas and result parsing.

``pages/wifi_input_descriptions.py`` deliberately avoids importing
``wifi_manager`` (and therefore ``sdbus``), so these run locally without D-Bus.

Uses the same ``sys.path`` loader discipline as ``test_camera_reducer.py`` and
imports ``WiFiType`` together with the parser so both reference the same class
object even after an integration test wipes ``sys.modules``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _load() -> tuple[Any, Any, Any, Any, Any]:
    modules_before = set(sys.modules)

    service_dir = str(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '030-wifi',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from pages.wifi_input_descriptions import (  # type: ignore[import-not-found]
        OTHER_OPTION,
        network_select_description,
        parse_full_result,
    )

    from ubo_app.store.input.types import InputMethod, InputResult
    from ubo_app.store.services.wifi import WiFiType

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return (
        InputMethod,
        InputResult,
        WiFiType,
        OTHER_OPTION,
        (network_select_description, parse_full_result),
    )


(
    InputMethod,
    InputResult,
    WiFiType,
    OTHER_OPTION,
    (network_select_description, parse_full_result),
) = _load()


def _result(data: dict[str, str]) -> Any:  # noqa: ANN401
    return InputResult(data=data, files={}, method=InputMethod.WEB_DASHBOARD)


def test_parse_full_result_nopass_is_enum() -> None:
    """A 'nopass' form value parses to the WiFiType.NOPASS enum, not a string.

    Regression: the value must be a real enum so the open-network short-circuit
    (``type != WiFiType.NOPASS``) does not wrongly demand a password.
    """
    _, _, wifi_type, _ = parse_full_result(_result({'SSID': 'Open', 'Type': 'nopass'}))
    assert wifi_type is WiFiType.NOPASS


def test_parse_full_result_secured() -> None:
    """SSID/password/type/hidden are extracted, with type as a WiFiType enum."""
    ssid, password, wifi_type, hidden = parse_full_result(
        _result(
            {
                'SSID': 'Home',
                'Password': 'secret',
                'Type': 'WPA2',
                'Hidden': 'true',
            },
        ),
    )
    assert (ssid, password, wifi_type, hidden) == (
        'Home',
        'secret',
        WiFiType.WPA2,
        True,
    )


def test_network_select_description_lists_scanned_plus_other() -> None:
    """The step-1 select offers each scanned SSID followed by the 'Other' option."""
    class _Net:
        def __init__(self, ssid: str) -> None:
            self.ssid = ssid

    description = network_select_description([_Net('A'), _Net('B')])
    options = description.fields[0].options
    assert options == ['A', 'B', OTHER_OPTION]
