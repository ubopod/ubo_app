"""Restoring port selections must survive values written by an older schema.

These keys once held a bare role string. ``Store.load_object`` returns scalars
as-is before it consults the requested ``output_type``, so such a value passes
straight through into state — and the first autorun to read ``.role`` off it
raises on every subsequent state change, which stops the kiosk menus updating
without any visible error.
"""

from __future__ import annotations

import pytest

from ubo_app.store.services.kiosk import (
    KioskPortRole,
    KioskPortSelection,
    _restore_port_selection,
)

_DEFAULT = KioskPortSelection(role=KioskPortRole.TERMINAL)


@pytest.mark.persistent_store({'kiosk:hdmi_a_1': 'browser'})
def test_a_legacy_role_string_falls_back_to_the_default() -> None:
    """The exact shape found on a real device: a bare role string."""
    restored = _restore_port_selection('kiosk:hdmi_a_1', _DEFAULT)

    assert isinstance(restored, KioskPortSelection)
    assert restored == _DEFAULT


@pytest.mark.persistent_store({'kiosk:hdmi_a_1': ['not', 'a', 'selection']})
def test_any_other_stray_shape_also_falls_back() -> None:
    """Not just strings — anything `load_object` lets through unconverted."""
    restored = _restore_port_selection('kiosk:hdmi_a_1', _DEFAULT)

    assert isinstance(restored, KioskPortSelection)
    assert restored == _DEFAULT


def test_a_missing_key_uses_the_default() -> None:
    """The ordinary first-boot path is unaffected."""
    restored = _restore_port_selection('kiosk:never_written', _DEFAULT)

    assert restored == _DEFAULT
